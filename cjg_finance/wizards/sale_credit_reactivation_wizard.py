# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class SaleCreditReactivationWizard(models.TransientModel):
    _name = 'sale.credit.reactivation.wizard'
    _description = 'Reactivación de Contrato'

    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        readonly=True,
    )
    step = fields.Selection([
        ('confirm', 'Confirmar'),
        ('apply', 'Aplicar'),
    ], string='Paso', default='confirm', required=True)

    current_state = fields.Char(
        string='Estado Actual',
        related='credit_id.process_state_label',
        readonly=True,
    )
    paid_capital = fields.Monetary(
        string='Capital Pagado',
        currency_field='currency_id',
        related='credit_id.process_capital_paid',
        readonly=True,
        help='Capital efectivamente aplicado en pagos, sin incluir intereses.',
    )
    pending_installments = fields.Integer(
        string='Cuotas Pendientes',
        related='credit_id.process_pending_installments',
        readonly=True,
    )
    penalty_rate = fields.Float(
        string='% Penalidad',
        required=True,
        default=30.0,
    )
    penalty_amount = fields.Monetary(
        string='Penalidad Total',
        currency_field='currency_id',
        compute='_compute_penalty_amount',
        readonly=True,
    )
    penalty_per_installment = fields.Monetary(
        string='Penalidad por Cuota',
        currency_field='currency_id',
        compute='_compute_penalty_amount',
        readonly=True,
    )
    suggested_penalty_rate = fields.Float(
        string='% Sugerido',
        compute='_compute_suggested_penalty_rate',
        help='% de penalidad sugerido por el sistema si el monto al 30% es elevado.',
    )
    suggested_penalty_reason = fields.Char(
        string='Razón de la Sugerencia',
        compute='_compute_suggested_penalty_rate',
    )
    penalty_rate_modified = fields.Boolean(
        string='% Modificado',
        default=False,
        help='True si el usuario cambió el % del 30% default.',
    )
    penalty_rate_justification = fields.Text(
        string='Justificación del Cambio de %',
        help='Obligatoria si penalty_rate != 30% (mínimo 20 caracteres).',
    )
    penalty_rate_approved_by = fields.Many2one(
        'res.users',
        string='Aprobado Por (Supervisor)',
        domain=lambda self: [
            ('share', '=', False),
            ('groups_id', 'in', [
                self.env.ref('cjg_finance.group_collection_manager').id,
                self.env.ref('cjg_finance.group_credit_manager').id,
            ]),
        ],
        help='Supervisor que autoriza el ajuste del % de penalidad.',
    )
    penalty_rate_approval_date = fields.Datetime(
        string='Fecha de Aprobación',
        readonly=True,
    )
    penalty_rate_auto_adjusted = fields.Boolean(
        string='Auto-ajuste Sugerido',
        default=False,
        help='True si el sistema sugirió un % menor por monto elevado.',
    )
    notes = fields.Text(string='Observaciones')
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id',
        readonly=True,
    )
    supervisor_authorized = fields.Boolean(
        string='Autorizado por Supervisor',
        default=False,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        credit = self.env['sale.credit'].browse(
            self.env.context.get('active_id') or values.get('credit_id')
        )
        if credit and credit.exists():
            values.setdefault('credit_id', credit.id)
            values.setdefault('penalty_rate', credit.process_default_penalty_rate or 30.0)
        return values

    @api.depends('paid_capital', 'penalty_rate', 'pending_installments', 'currency_id')
    def _compute_penalty_amount(self):
        for wizard in self:
            currency = wizard.currency_id or wizard.env.company.currency_id
            total = currency.round(
                (wizard.paid_capital or 0.0) * ((wizard.penalty_rate or 0.0) / 100.0)
            )
            wizard.penalty_amount = total
            n = wizard.pending_installments or 1
            wizard.penalty_per_installment = currency.round(total / n) if n else 0.0

    @api.constrains('penalty_rate')
    def _check_penalty_rate_range(self):
        for wizard in self:
            if wizard.penalty_rate < 0 or wizard.penalty_rate > 100:
                raise ValidationError(_(
                    'La penalidad debe estar entre 0%% y 100%%. Valor actual: %s%%'
                ) % wizard.penalty_rate)

    @api.onchange('penalty_rate')
    def _onchange_penalty_rate(self):
        """Marca penalty_rate_modified si el usuario cambió el % del default 30%."""
        for wizard in self:
            wizard.penalty_rate_modified = abs(wizard.penalty_rate - 30.0) > 0.01

    @api.depends('penalty_amount', 'credit_id')
    def _compute_suggested_penalty_rate(self):
        """Sugiere un % menor si la penalidad al 30% es muy elevada.

        Regla: si penalty_amount > 5 * valor_cuota_promedio, sugerir 20%.
        Si penalty_amount > 8 * valor_cuota_promedio, sugerir 15%.

        NO modifica el penalty_rate — solo sugiere.
        """
        for wizard in self:
            if not wizard.credit_id or not wizard.penalty_amount:
                wizard.suggested_penalty_rate = 30.0
                wizard.suggested_penalty_reason = ''
                wizard.penalty_rate_auto_adjusted = False
                continue
            unpaid_lines = wizard.credit_id.credit_lines.filtered(
                lambda l: l.state not in ('paid', 'cancelled')
            )
            if not unpaid_lines:
                wizard.suggested_penalty_rate = 30.0
                wizard.suggested_penalty_reason = ''
                wizard.penalty_rate_auto_adjusted = False
                continue
            amounts = unpaid_lines.mapped('amount_fixed') or [0.0]
            avg_installment = sum(amounts) / len(amounts)
            threshold_5 = 5 * avg_installment
            threshold_8 = 8 * avg_installment
            if wizard.penalty_amount > threshold_8:
                wizard.suggested_penalty_rate = 15.0
                wizard.suggested_penalty_reason = _(
                    "La penalidad al 30%% (%.2f) excede 8 cuotas del valor promedio. "
                    "Se sugiere 15%% (%.2f) por monto elevado."
                ) % (wizard.penalty_amount, wizard.penalty_amount * 0.5)
                wizard.penalty_rate_auto_adjusted = True
            elif wizard.penalty_amount > threshold_5:
                wizard.suggested_penalty_rate = 20.0
                wizard.suggested_penalty_reason = _(
                    "La penalidad al 30%% (%.2f) excede 5 cuotas del valor promedio. "
                    "Se sugiere 20%% (%.2f) por monto elevado."
                ) % (wizard.penalty_amount, wizard.penalty_amount * (2.0 / 3.0))
                wizard.penalty_rate_auto_adjusted = True
            else:
                wizard.suggested_penalty_rate = 30.0
                wizard.suggested_penalty_reason = ''
                wizard.penalty_rate_auto_adjusted = False

    def _validate_eligibility(self):
        """Validate that the contract is eligible for reactivation."""
        self.ensure_one()
        if self.credit_id.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para reactivación. '
                'Solo contratos en estado Anulado o Desistido pueden ser reactivados. '
                'Estado actual: %s'
            ) % (self.credit_id.name, self.credit_id.process_state_label))

    def action_confirm(self):
        """Step 1: Validate and show summary."""
        self.ensure_one()
        self._validate_eligibility()
        if self.penalty_rate < 0:
            raise ValidationError(_('La penalidad no puede ser negativa.'))
        self.step = 'apply'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_apply_reactivation(self):
        """Step 2: Create CRM lead for reactivation."""
        self.ensure_one()
        self._validate_eligibility()

        # Validar rango del penalty_rate
        if self.penalty_rate < 0 or self.penalty_rate > 100:
            raise ValidationError(_('La penalidad debe estar entre 0%% y 100%%.'))

        # Si el % fue modificado del default 30%, exigir justificación + aprobación
        if abs(self.penalty_rate - 30.0) > 0.01:
            if not self.penalty_rate_justification or len(self.penalty_rate_justification.strip()) < 20:
                raise ValidationError(_(
                    "Si modifica el porcentaje de penalidad del 30%% default, "
                    "debe proporcionar una justificación de al menos 20 caracteres. "
                    "Justificación actual: '%s'"
                ) % (self.penalty_rate_justification or ''))
            if not self.penalty_rate_approved_by:
                raise ValidationError(_(
                    "Si modifica el porcentaje de penalidad, debe indicar el supervisor "
                    "que autoriza el cambio."
                ))
            manager_groups = (
                self.env.ref('cjg_finance.group_collection_manager')
                | self.env.ref('cjg_finance.group_credit_manager')
            )
            if not any(
                group in self.penalty_rate_approved_by.groups_id
                for group in manager_groups
            ):
                raise ValidationError(_(
                    'El aprobador debe ser gerente de Crédito o de Cobros.'
                ))
            if (
                self.credit_id.company_id
                and self.credit_id.company_id
                not in self.penalty_rate_approved_by.company_ids
            ):
                raise ValidationError(_(
                    'El supervisor no está autorizado para la empresa del contrato.'
                ))
            if not self.penalty_rate_approval_date:
                self.penalty_rate_approval_date = fields.Datetime.now()

        # Check if penalty_rate was modified from default
        default_rate = self.credit_id.process_default_penalty_rate or 30.0
        if abs(self.penalty_rate - default_rate) > 0.01:
            # Log supervisor authorization in chatter
            self.credit_id.message_post(
                body=_(
                    'Tasa de penalidad de reactivación modificada de %s%% a %s%% '
                    'por autorización del usuario %s.<br/>'
                    'Aprobado por supervisor: %s<br/>'
                    'Fecha de aprobación: %s<br/>'
                    'Justificación: %s'
                ) % (
                    default_rate, self.penalty_rate, self.env.user.name,
                    self.penalty_rate_approved_by.name if self.penalty_rate_approved_by else 'N/A',
                    self.penalty_rate_approval_date or 'N/A',
                    self.penalty_rate_justification or '',
                )
            )

        # Create CRM lead for reactivation
        lead_vals = {
            'name': _('Reactivación: %s') % self.credit_id.name,
            'partner_id': self.credit_id.partner_id.id,
            'contract_process_type': 'reactivation',
            'origin_sale_credit_id': self.credit_id.id,
            'reactivation_penalty_rate': self.penalty_rate,
            'reactivation_penalty_amount': self.penalty_amount,
            'capitalized_amount': self.paid_capital,
            'company_id': self.credit_id.company_id.id,
        }
        if self.notes:
            lead_vals['description'] = self.notes

        lead = self.env['crm.lead'].create(lead_vals)

        self.credit_id.message_post(
            body=_(
                'Proceso de reactivación iniciado. '
                'Planilla CRM creada: <a href="#id=%d&model=crm.lead">%s</a><br/>'
                'Penalidad: %s%% = %s<br/>'
                'Penalidad por cuota: %s'
            ) % (
                lead.id, lead.name,
                self.penalty_rate, self.penalty_amount,
                self.penalty_per_installment,
            )
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Planilla de Reactivación'),
            'res_model': 'crm.lead',
            'res_id': lead.id,
            'view_mode': 'form',
            'target': 'current',
        }
