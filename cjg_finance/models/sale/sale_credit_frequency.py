from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleCreditFrequency(models.Model):
    _name = "sale.credit.frequency"
    _description = "Frecuencia"

    name = fields.Char(string="Name", required=True)
    type = fields.Selection([('day', 'Dias'), ('week', 'Semanas'), 
    ('month', 'Mensual'), ('year', 'Años'),], string='periodicidad', default='day', required=True)
    interval = fields.Integer(string="Intervalo",default=1, required=True)
    installment_ids = fields.Many2many(string='Cuotas', comodel_name='sale.credit.installment', required=True, help="Payments causing this error")
    description = fields.Text(string="Descripcion", required=True)

    @api.constrains('interval')
    def check_to_interval(self):
        if self.interval < 1:
            raise ValidationError(_('El "Intervalo" no puede ser menor que "1"')) 

