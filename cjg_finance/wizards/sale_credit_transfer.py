from odoo import fields, models,api

class SaleCreditCancelWizard(models.TransientModel):
    _name = 'sale.credit.transfer.wizard'
    _description = 'Tranferir solicitud de credito'


    transfer_partner_id = fields.Many2one('res.partner', string="Cliente",required=True)
    transfer_ref_partner_id = fields.Many2one('res.partner', string="Referencia Personal")
    transfer_cob_debtor_id = fields.Many2one('res.partner', string="Codeudor")

    reason_cancellation = fields.Text(string='Razon del traspaso', required=True)

    
    def action_confirm(self):

        credit_model = self.env['sale.credit']
        active_id = self._context.get('active_id')
        credit_record = credit_model.browse(active_id)       
        
        today = fields.Date.today()
        credit_record.write({
            'error_log': f'Cambiado por {self.env.user.name} : {today} : traspasado de {credit_record.partner_id.name} a {self.transfer_partner_id.name} motivo de : {self.reason_cancellation}'
        })
        
        credit_record.write({
            'partner_id': self.transfer_partner_id.id,
            'ref_partner_id': self.transfer_ref_partner_id.id,
            'co_debtor_id': self.transfer_cob_debtor_id.id

            })

        credit_lines = self.env['sale.credit.line'].search([('credit_id', '=', credit_record.id)])
        credit_lines.write({'partner_id': self.transfer_partner_id.id})
        
        credit_record.valid_balance_user()

