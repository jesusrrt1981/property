# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class SaleCreditDevolucionWizard(models.TransientModel):
    _name = 'sale.credit.devolucion.wizard'
    _description = 'Wizard de Devolución (Opción 3)'

    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        readonly=True,
    )
    step = fields.Selection([
        ('confirm', 'Confirmar Inicio'),
        ('register', 'Registrar Emisión'),
    ], string='Paso', default='confirm', required=True)

    capital_paid = fields.Monetary(
        string='Capital Pagado',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
    )
    interest_paid = fields.Monetary(
        string='Interés Pagado',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
    )
    devolucion_amount = fields.Monetary(
        string='Monto a Devolver (70%)',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
    )
    retained_amount = fields.Monetary(
        string='Monto Retenido (30% + Intereses)',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
    )
    devolucion_method = fields.Selection([
        ('cheque', 'Cheque'),
        ('transfer', 'Transferencia Bancaria'),
    ], string='Método de Devolución', required=True, default='cheque')
    devolucion_reference = fields.Char(string='Número de Referencia / Cheque')
    devolucion_date = fields.Date(string='Fecha de Emisión')
    devolucion_notes = fields.Text(string='Notas Adicionales')
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id',
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        credit = self.env['sale.credit'].browse(
            self.env.context.get('active_id') or values.get('credit_id')
        )
        if credit and credit.exists():
            values.setdefault('credit_id', credit.id)
        return values

    @api.depends('credit_id')
    def _compute_amounts(self):
        for wizard in self:
            if wizard.credit_id:
                capital = wizard.credit_id.process_capital_paid or 0.0
                interest = wizard.credit_id.process_interest_paid or 0.0
                currency = wizard.currency_id or wizard.env.company.currency_id
                devolucion = currency.round(capital * 0.70)
                retained = currency.round(capital * 0.30 + interest)
                wizard.capital_paid = capital
                wizard.interest_paid = interest
                wizard.devolucion_amount = devolucion
                wizard.retained_amount = retained
            else:
                wizard.capital_paid = 0.0
                wizard.interest_paid = 0.0
                wizard.devolucion_amount = 0.0
                wizard.retained_amount = 0.0

    def _validate_eligibility(self):
        """Validate contract is eligible for devolucion."""
        self.ensure_one()
        credit = self.credit_id
        if credit.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para devolución. '
                'Solo contratos en estado Anulado o Desistido pueden solicitar devolución.'
            ) % credit.name)
        if not credit.date_start:
            raise UserError(_('El contrato %s no tiene fecha de inicio registrada.') % credit.name)
        months_old = (date.today() - credit.date_start).days / 30.44
        if months_old < 12:
            raise UserError(_(
                'El contrato %s no cumple el requisito mínimo de antigüedad. '
                'Se requieren al menos 12 meses desde la fecha de inicio (%s). '
                'Antigüedad actual: %.1f meses.'
            ) % (credit.name, credit.date_start, months_old))

    def _get_business_days_deadline(self, days=5):
        """Calculate deadline skipping weekends."""
        current = date.today()
        added = 0
        while added < days:
            current += timedelta(days=1)
            if current.weekday() < 5:  # Monday=0, Friday=4
                added += 1
        return current

    def action_confirm_devolucion(self):
        """Step 1: Validate, change process_detail_status, create mail.activity."""
        self.ensure_one()
        self._validate_eligibility()

        credit = self.credit_id
        # Determine new process_detail_status
        new_status = 'anulado_devolucion' if credit.state == 'cancelled' else 'desistido_devolucion'
        credit.write({'process_detail_status': new_status})

        # Create mail.activity for Documentación department
        deadline = self._get_business_days_deadline(5)
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        activity_vals = {
            'res_model_id': self.env['ir.model']._get('sale.credit').id,
            'res_id': credit.id,
            'activity_type_id': activity_type.id if activity_type else self.env['mail.activity.type'].search([], limit=1).id,
            'summary': _('Procesar Devolución: %s') % credit.name,
            'note': _(
                'Monto a devolver: %s (%s)<br/>'
                'Método: %s<br/>'
                'Fecha límite: %s'
            ) % (
                self.devolucion_amount,
                self.devolucion_method,
                dict(self._fields['devolucion_method'].selection).get(self.devolucion_method, ''),
                deadline,
            ),
            'date_deadline': deadline,
            'user_id': self.env.user.id,
        }
        self.env['mail.activity'].create(activity_vals)

        credit.message_post(
            body=_(
                'Proceso de devolución iniciado.<br/>'
                'Capital pagado: %s<br/>'
                'Monto a devolver (70%%): %s<br/>'
                'Monto retenido (30%% + intereses): %s<br/>'
                'Método solicitado: %s<br/>'
                'Actividad creada con fecha límite: %s'
            ) % (
                self.capital_paid,
                self.devolucion_amount,
                self.retained_amount,
                dict(self._fields['devolucion_method'].selection).get(self.devolucion_method, ''),
                deadline,
            )
        )

        # Advance to register step
        self.step = 'register'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_register_devolucion(self):
        """Step 2: Register reference/date and finalize."""
        self.ensure_one()
        if not self.devolucion_reference:
            raise ValidationError(_(
                'Debe ingresar el número de referencia del cheque o transferencia.'
            ))
        if not self.devolucion_date:
            raise ValidationError(_('Debe ingresar la fecha de emisión.'))

        credit = self.credit_id
        credit.write({
            'devolucion_method': self.devolucion_method,
            'devolucion_reference': self.devolucion_reference,
            'devolucion_date': self.devolucion_date,
            'devolucion_amount': self.devolucion_amount,
            'devolucion_notes': self.devolucion_notes,
        })

        credit.message_post(
            body=_(
                'Devolución registrada.<br/>'
                'Monto devuelto: %s<br/>'
                'Método: %s<br/>'
                'Referencia: %s<br/>'
                'Fecha de emisión: %s'
            ) % (
                self.devolucion_amount,
                dict(self._fields['devolucion_method'].selection).get(self.devolucion_method, ''),
                self.devolucion_reference,
                self.devolucion_date,
            )
        )

        return {'type': 'ir.actions.act_window_close'}
