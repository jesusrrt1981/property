from odoo import models, fields


class SaleCredit(models.Model):
    _inherit = 'sale.credit'

    # Ensure these related fields are stored so they can be used in read_group
    percent_interest = fields.Float(
        related='category_id.percent_interest', store=True, readonly=True, string="TAE(%)")

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', store=True, readonly=True)