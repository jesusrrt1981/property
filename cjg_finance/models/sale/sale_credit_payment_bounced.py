# -*- coding: utf-8 -*-

from odoo import fields, models


class SaleCreditPaymentBounced(models.Model):
    """Cheque devuelto sobre un pago aplicado (Testarossa: caja/chequedevuelto).

    El pago se anula con el flujo canónico (action_cancel revierte asientos y
    cuotas) y se marca como cheque devuelto, con cargo opcional al contrato.
    """
    _inherit = 'sale.credit.payment'

    bounced_check = fields.Boolean(
        string='Cheque Devuelto', readonly=True, copy=False)
    bounce_date = fields.Date(
        string='Fecha Devolución', readonly=True, copy=False)
    bounce_reason = fields.Char(
        string='Motivo Devolución', readonly=True, copy=False)
    bounce_check_number = fields.Char(
        string='Cheque No.', readonly=True, copy=False)
    bounce_bank = fields.Char(
        string='Banco', readonly=True, copy=False)
    bounce_fee = fields.Float(
        string='Cargo por Devolución', readonly=True, copy=False)

    def action_open_bounced_check_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registrar Cheque Devuelto',
            'res_model': 'bounced.check.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_payment_id': self.id},
        }

    def print_bounced_check_receipt(self):
        return self.env.ref(
            'cjg_finance.action_report_bounced_check_receipt').report_action(self)
