from odoo import api, fields, models
from odoo.exceptions import ValidationError, RedirectWarning, UserError
class SaleOrder(models.Model):

    _inherit = 'sale.order'

    pricelist_id = fields.Many2one('product.pricelist', check_company=False)
    fiscal_position_id = fields.Many2one('account.fiscal.position', check_company=False)

    credit_amount = fields.Monetary(compute='_credit_total', string="Importe del Crédito")
    credit_count = fields.Integer(string="Crédito")
    credit_id = fields.Many2one('sale.credit', string='Credito')
    credit_state = fields.Selection(related="credit_id.state", string="Estado de Pago")
    journal_id = fields.Many2one('account.journal', string="Diario")
    sale_advanced = fields.Boolean(string="Financiar?", readonly=True)
     
    def action_show_requested_credit(self):
        if self.credit_amount == 0:
            self.ensure_one()
            return {
                'type': 'ir.actions.act_window',
                'target': 'current',
                'name': 'Sales Credit',
                'view_mode': 'form',
                'res_model': 'sale.credit',
                'domain': [('sale_id', '=', self.id)],
            }

        else:
            self.ensure_one()
            return {
                'type': 'ir.actions.act_window',
                'target': 'current',
                'name': 'Sales Credit',
                'view_mode': 'tree',
                'res_model': 'sale.credit.line',
                'domain': [('sale_id', '=', self.id)],
            }

    def _credit_total(self):
        self.credit_amount = 0
        # self.credit_id
        domain = [
            ('sale_id', '=', self.id)
        ]
        price_total = self.env['sale.credit'].search(domain)
        self.credit_amount = price_total.amount_total if price_total.amount_total else 0
