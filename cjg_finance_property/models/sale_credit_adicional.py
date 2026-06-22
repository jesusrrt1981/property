from odoo import fields, models

class SaleCreditAdicional(models.Model):
    _name = 'sale.credit.adicional'
    _description = 'Adicional de Crédito'

    name = fields.Char(string='Adicional')
    sale_credit_id = fields.Many2one('sale.credit', string='Crédito')
    adicional_id = fields.Many2one('product.template')
    price_fixed_usd = fields.Float(string="Precio Fijo USD")
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    project_property_id_adicional = fields.Many2one(
        'property.sub.project',
        string="Proyecto",
        related='adicional_id.project_property_id_adicional',
        store=True
    )
    date_adicional = fields.Date(string="Fecha Adicional", default=fields.Date.today())