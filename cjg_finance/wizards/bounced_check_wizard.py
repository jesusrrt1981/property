# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class BouncedCheckWizard(models.TransientModel):
    """Registrar un cheque devuelto: anula el pago (revierte cuotas y
    asientos), marca el recibo y aplica el cargo al contrato."""
    _name = 'bounced.check.wizard'
    _description = 'Registrar Cheque Devuelto'

    payment_id = fields.Many2one(
        'sale.credit.payment', string='Pago/Recibo', required=True,
        domain="[('state', '=', 'paid')]")
    credit_id = fields.Many2one(
        related='payment_id.credit_id', string='Contrato')
    partner_id = fields.Many2one(
        related='payment_id.partner_id', string='Cliente')
    bounce_date = fields.Date(
        string='Fecha Devolución', required=True, default=fields.Date.today)
    check_number = fields.Char(string='Cheque No.', required=True)
    bank = fields.Char(string='Banco')
    reason = fields.Char(
        string='Motivo', required=True,
        default='Cheque devuelto por el banco')
    fee_amount = fields.Float(
        string='Cargo por Devolución',
        help='Cargo que se aplicará al contrato por el cheque devuelto. '
             '0 para no aplicar cargo.')

    @api.constrains('fee_amount')
    def _check_fee(self):
        for rec in self:
            if rec.fee_amount < 0:
                raise UserError(_('El cargo no puede ser negativo.'))

    def action_confirm(self):
        self.ensure_one()
        payment = self.payment_id

        if payment.state != 'paid':
            raise UserError(_('Solo se puede devolver un pago aplicado (estado Pagado).'))
        if payment.bounced_check:
            raise UserError(_('Este pago ya fue marcado como cheque devuelto.'))

        reason = _('CHEQUE DEVUELTO No. %s — %s') % (self.check_number, self.reason)

        # Anular con el flujo canónico: revierte asientos y aplicación a cuotas
        payment.action_cancel(reason=reason)

        payment.write({
            'bounced_check': True,
            'bounce_date': self.bounce_date,
            'bounce_reason': self.reason,
            'bounce_check_number': self.check_number,
            'bounce_bank': self.bank,
            'bounce_fee': self.fee_amount,
        })

        # Cargo por cheque devuelto sobre el contrato
        if self.fee_amount and payment.credit_id:
            self.env['sale.credit.charge'].create({
                'name': _('CHD %s') % (payment.name or ''),
                'credit_id': payment.credit_id.id,
                'charge_type': 'charge',
                'amount': self.fee_amount,
                'reason': reason,
                'date': self.bounce_date,
            })

        if payment.credit_id:
            payment.credit_id.message_post(body=_(
                'Cheque devuelto: recibo %s, cheque No. %s (%s). '
                'Pago revertido%s.') % (
                payment.name, self.check_number, self.bank or '',
                _(' y cargo de %s aplicado') % self.fee_amount if self.fee_amount else ''))

        return payment.print_bounced_check_receipt()
