
from odoo import fields, models,api

class SaleCreditCancelWizard(models.TransientModel):
    _name = 'sale.credit.refuse.wizard'
    _description = 'Rechazo de solicitud de credito'


    reason_cancellation = fields.Text(string='Razon de rechazo', required=True)

    def action_confirm(self):
        credit_model = self.env['sale.credit']
        active_id = self._context.get('active_id')
        credit_record = credit_model.browse(active_id)
        credit_record.refuse()
        today=fields.Date.today()
        reason_cancellation = self.reason_cancellation
        credit_record.write({'error_log': f'Rechazada por {self.env.user.name}: {reason_cancellation} Fecha de rechazo {today} '})