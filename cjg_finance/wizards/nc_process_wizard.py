# -*- coding: utf-8 -*-
"""
TRACK 5 (F5) — Wizard: Procesar NC (Nota de Crédito) con Script.

Replica el flujo del legacy:
    testarossa/modulos/cobros/view/view_nota_credito_pago.php
    testarossa/modulos/cobros/includeFacturaNCScript

El legacy permite "procesar" una NC después de creada:
    1. Asigna la NC al contrato.
    2. Ajusta los saldos de las cuotas (descuenta el monto de la NC).
    3. Crea líneas de accounting (movimiento de caja) que aplican la NC.
    4. Genera el comprobante en el cliente.

Diseño Odoo:
    - Wizard `nc.process.wizard` toma una NC (account.move out_refund) y la
      asigna a un contrato + ajusta saldos.
    - action_process() crea `account.move.line` en el contrato (vía
      `sale.credit.line` con `adjustment_line`).
    - action_open_contrato() abre el contrato afectado.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class NcProcessWizard(models.TransientModel):
    """
    Wizard que toma una NC y la "procesa" asignándola al contrato,
    ajustando saldos de cuotas y creando la línea contable.
    """
    _name = 'nc.process.wizard'
    _description = 'Wizard: Procesar NC (Asignar a Contrato)'

    move_id = fields.Many2one(
        'account.move',
        string='Nota de Crédito',
        required=True,
        domain="[('move_type', '=', 'out_refund'), ('state', '=', 'draft')]",
        ondelete='cascade',
    )
    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato a Asignar',
        required=True,
        help='Contrato al que se asignará esta NC.',
    )
    credit_line_id = fields.Many2one(
        'sale.credit.line',
        string='Línea de Crédito (cuota)',
        domain="[('credit_id', '=', credit_id)]",
        help='Cuota específica a la que se aplica. Si se deja vacío, se '
             'aplica a la próxima cuota pendiente del contrato.',
    )
    amount = fields.Float(
        string='Monto a Aplicar',
        required=True,
        digits='Account',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company,
    )
    note = fields.Text(
        string='Nota / Observación',
        help='Comentario que se añadirá al chatter del contrato.',
    )
    processed = fields.Boolean(
        string='Procesada',
        readonly=True,
        default=False,
        copy=False,
    )
    adjustment_id = fields.Many2one(
        'sale.credit.adjustment',
        string='Ajuste Generado',
        readonly=True,
        copy=False,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'move_id' in fields_list and not res.get('move_id'):
            active_id = self.env.context.get('active_id')
            if active_id:
                move = self.env['account.move'].browse(active_id)
                if move.exists() and move.move_type == 'out_refund':
                    res['move_id'] = move.id
                    if not res.get('amount'):
                        res['amount'] = move.amount_total
                    if not res.get('currency_id'):
                        res['currency_id'] = move.currency_id.id
        return res

    @api.onchange('move_id')
    def _onchange_move_id(self):
        if self.move_id and not self.amount:
            self.amount = self.move_id.amount_total
        if self.move_id and not self.currency_id:
            self.currency_id = self.move_id.currency_id

    @api.onchange('credit_id')
    def _onchange_credit_id(self):
        if self.credit_id:
            # Auto-seleccionar próxima cuota pendiente
            next_line = self.env['sale.credit.line'].search([
                ('credit_id', '=', self.credit_id.id),
                ('state', 'in', ('pending', 'paid_overdue')),
            ], order='expected_date_payment asc', limit=1)
            if next_line and not self.credit_line_id:
                self.credit_line_id = next_line

    def action_process(self):
        """
        Procesa la NC:
        1. Crea un `sale.credit.adjustment` (NC) ligado al contrato.
        2. Aplica el monto a la cuota (reduce `amount_residual`).
        3. Publica un chatter en el contrato.
        4. Marca la NC como "asignada a contrato".
        """
        self.ensure_one()
        if self.processed:
            raise UserError(_('Esta NC ya fue procesada.'))
        if not self.credit_id:
            raise UserError(_('Debe seleccionar un contrato.'))
        if self.amount <= 0:
            raise UserError(_('El monto a aplicar debe ser mayor a 0.'))
        if self.amount > self.move_id.amount_total:
            raise UserError(_(
                'El monto a aplicar (%(apply).2f) no puede superar el monto '
                'de la NC (%(nc).2f).'
            ) % {
                'apply': self.amount,
                'nc': self.move_id.amount_total,
            })

        # 1. Crear el adjustment (NC) en cjg_finance
        adjustment_vals = {
            'credit_id': self.credit_id.id,
            'credit_line_id': self.credit_line_id.id if self.credit_line_id else False,
            'adjustment_type': 'credit_note',
            'amount': self.amount,
            'date': fields.Date.today(),
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'ref': 'NC: %s' % (self.move_id.name or self.move_id.display_name),
        }
        adjustment = self.env['sale.credit.adjustment'].create(adjustment_vals)

        # 2. Aplicar el monto a la cuota (reduce amount_residual)
        if self.credit_line_id:
            new_residual = max(
                (self.credit_line_id.amount_residual or 0.0) - self.amount,
                0.0,
            )
            self.credit_line_id.write({
                'amount_residual': new_residual,
                'amount_paid_total': (
                    (self.credit_line_id.amount_paid_total or 0.0) + self.amount
                ),
            })

        # 3. Chatter en el contrato
        self.credit_id.message_post(
            body=_(
                '<b>NC procesada y asignada al contrato:</b><br/>'
                '<b>NC:</b> %s<br/>'
                '<b>Monto:</b> %s %s<br/>'
                '<b>Cuota:</b> %s<br/>'
                '<b>Ajuste:</b> %s<br/>'
                '<b>Por:</b> %s<br/>'
                '<b>Nota:</b> %s'
            ) % (
                self.move_id.display_name,
                self.currency_id.symbol or '',
                '{:,.2f}'.format(self.amount),
                self.credit_line_id.display_name if self.credit_line_id else 'N/A',
                adjustment.display_name,
                self.env.user.name,
                self.note or '(sin nota)',
            ),
            subject=_('NC procesada'),
        )

        # 4. Chatter en la NC
        self.move_id.message_post(
            body=_(
                '<b>NC procesada por el wizard:</b><br/>'
                '<b>Contrato:</b> %s<br/>'
                '<b>Monto aplicado:</b> %s %s<br/>'
                '<b>Ajuste:</b> %s'
            ) % (
                self.credit_id.display_name,
                self.currency_id.symbol or '',
                '{:,.2f}'.format(self.amount),
                adjustment.display_name,
            ),
            subject=_('NC aplicada a contrato'),
        )

        self.write({
            'processed': True,
            'adjustment_id': adjustment.id,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('NC procesada'),
                'message': _(
                    'NC %(nc)s aplicada al contrato %(contract)s. '
                    'Ajuste: %(adj)s.'
                ) % {
                    'nc': self.move_id.display_name,
                    'contract': self.credit_id.display_name,
                    'adj': adjustment.display_name,
                },
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Contrato'),
                    'res_model': 'sale.credit',
                    'view_mode': 'form',
                    'res_id': self.credit_id.id,
                },
            },
        }

    def action_open_contrato(self):
        """Abre el contrato seleccionado (para asignación manual)."""
        self.ensure_one()
        if not self.credit_id:
            raise UserError(_('Debe seleccionar un contrato primero.'))
        return {
            'name': _('Contrato'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit',
            'view_mode': 'form',
            'res_id': self.credit_id.id,
            'target': 'current',
        }
