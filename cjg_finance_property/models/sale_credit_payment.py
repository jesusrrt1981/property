import datetime
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
import math

class SaleCreditPayment(models.Model):
    _inherit = 'sale.credit.payment'
    
    # project_property_id removed - no longer needed with new property_product_ids structure


    # def create_account_payment(self):
    #     if self.company_id.currency_id != self.currency_id:
    #         activa = True
    #     else:
    #         activa = False
    #     if self.amount_divisas > 0 and self.is_currency_id_different == True:
    #         balance=self.amount_divisas
    #     else:
    #         balance=self.amount_total
    #     self.payment_id = self.env['account.payment'].create({
    #         'payment_type': 'inbound',
    #         'partner_id': self.partner_id.id,
    #         'amount': balance ,
    #         'date': self.payment_date,
    #         'journal_id': self.journal_id.id,
    #         'state': 'draft',
    #         'sale_credit_id': self.credit_id.id,
    #         'sale_credit_payment_id': self.id,
    #         'ref':f'{self.credit_id.name}/{self.name}',
    #         'currency_id':self.currency_id.id,
    #         'sale_credit_payment':True
    #     })
        
    #     # dest_account_id = self.project_property_id.credit_account_advanced_id
    #     # if dest_account_id:
    #     #     self.payment_id.destination_account_id = dest_account_id.id
            
    #     self.apply_payment_lines(self.payment_id.id)
    #     self.credit_id.payment_ids = [(4, self.payment_id.id)]
    #     self.payment_id.action_post()
    #     self.update_credit_lines()
    #     self.state = 'paid'
    #     self.credit_id.optimization_dinamic()
    #     self.remanente_calculate()