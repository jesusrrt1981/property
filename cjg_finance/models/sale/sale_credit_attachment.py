from odoo import models, fields, api

class SaleCreditAttachment(models.Model):
    _name = 'sale.credit.attachment'
    _description = 'Sale Credit Attachment'
    
    description = fields.Text(string="Descripción")
    file_attached = fields.Binary('Fichero')
    file_attached_name = fields.Char(string="Nombre del Fichero")
    file_name_show = fields.Char(string="Nombre Mostrado")
    sale_payment_id = fields.Many2one("sale.credit.payment", string="Pagos de Crédito")
    credit_id = fields.Many2one("sale.credit", string="Crédito")
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)