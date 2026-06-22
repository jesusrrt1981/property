from odoo import api, fields, models
from odoo.exceptions import ValidationError, RedirectWarning, UserError


class credit_preapproved(models.Model):
    _name = 'sale_credit.preaprovado'
    _description = 'Preaprovado'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Solicitud')
    client = fields.Many2one('res.partner', string='Cliente')
    credit_preapproved = fields.Float(string="Balance pre-aprobado")
    balance_credit = fields.Float(compute='_credit_balance', string="Balance Restante")

    def _credit_balance(self):
        for recor in self:
            recor.name = f'Sc: {recor.client.name} '
            client_balance = recor.env['sale.credit'].search(
                [('partner_id', '=', recor.client.id), ('state', 'not in', ['refuse', 'cancelled'])])
            list_balance = []
            for record in client_balance:
                list_balance.append(record.total_sold)
            balance = (recor.credit_preapproved - sum(list_balance))
            recor.balance_credit = balance
