# -*- coding: utf-8 -*-
#################################################################################
# Author      : Acespritech Solutions Pvt. Ltd. (<www.acespritech.com>)
# Copyright(c): 2012-Present Acespritech Solutions Pvt. Ltd.
# All Rights Reserved.
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#################################################################################

from odoo import fields, models, api, _
import datetime
from dateutil.relativedelta import relativedelta
from odoo.exceptions import Warning, ValidationError
import numpy as np
import numpy_financial as fn


class loan_calc(models.Model):
    _name = 'loan.calc'
    _description = 'Loan Calc'

    global flag
    flag = 0

    def get_payment_data(self):
        
        global flag
        if not self.term:
            raise Warning(_('You must enter the term for loan.'))
        payment_list = []
        if self._context.get('active_id'):
            loan_app_rec = self.env['loan.application'].browse([self._context.get('active_id')])
            if loan_app_rec.state != 'approved':
                raise Warning(_("You can't create the payments because loan still not approved."))
            if loan_app_rec.state == 'approved' and flag == 0:
                flag = 1
                raise Warning(_('Are you sure you want to calculate the emi based on this amount %d.'
                               % (self.loan_amount)))
            for line in self.loan_calc_line_ids:
                if line.due_date:
                    loan_due_date = line.due_date.strftime('%m-%Y')
                rate = 2
                value = {
                    'original_due_date': line.due_date,
                    'due_date': line.due_date,
                    'rate': rate,
                    'principal': line.principal,
                    'interest': line.interest,
                    'total': line.total,
                    'balance_amt': line.balance_amt,
                    'loan_app_id': loan_app_rec.id,
                }
                payment_list.append((0, 0, value))
            if flag == 1:
                loan_app_rec.write({
                    'loan_payment_ids': payment_list,
                    'no_of_installment': len(payment_list),
                    'term': self.term,
                    'rate': 2,
                    'state': 'emi_calculated'
                })

    @api.depends('loan_calc_line_ids.principal', 'loan_calc_line_ids.interest')
    def _amount_all(self):
        for each in self:
            total_principal = principal = interest = 0.0
            if each.method == 'flat' and self.loan_amount and self.method:
                for each_line in self.loan_calc_line_ids:
                    total_principal += each_line.principal
                principal = each.loan_amount
                interest = 2 / 100 * each.loan_amount
                amt_disp = (float(self.term) / 12) * interest
                interest = amt_disp
            else:
                for line in each.loan_calc_line_ids:
                    principal += line.principal
                    interest += line.interest
            each.update({
                'principal_amount': principal,
                'interest_amount': interest,
                'total_amount': principal + interest,
            })

    @api.constrains('loan_amount')
    def check_validation_exception_date_ids(self):
         if self.loan_type_id:
            if self.loan_type_id.maximum_amount < self.loan_amount:
                raise ValidationError(_('Loan amount exceed the limit %d.' % (self.loan_type_id.maximum_amount)))
            if self.loan_type_id.maximum_term < self.term:
                raise ValidationError(_('Loan term exceed the limit %d.' % (self.loan_type_id.maximum_term)))
            if self.loan_type_id.minimum_term > self.term:
                raise ValidationError(_('Loan term limit should be greater then or equal to then %d.' % (self.loan_type_id.minimum_term)))
            if self.loan_type_id.minimum_amount > self.loan_amount and self.loan_amount:
                raise ValidationError(_('The amount you entered is lower than the minimum amount %d.'
                                   % (self.loan_type_id.minimum_amount)))

   
        
               
          
    @api.depends('term', 'loan_amount', 'method', 'rate')
    def compute_due_date(self):
       
        self.loan_calc_line_ids = False
            
        
        if self.loan_amount<0:
           raise ValidationError(_('colocar un valor no puede ser negativo'))
        else:
            date_list = []
            if self.method == 'reducing':
                # if self.loan_amount<=0:
                #      raise ValidationError(_('colocar un valor [simple] diferente de cero'))
                principal = self.loan_amount
                saldo = self.loan_amount
                months = self.term
                rate = self.rate/ 100.00 if self.rate else 0
                per = np.arange(months) + 1
                
                ipmt = fn.ipmt(rate / 12, per, months, principal)
                ppmt = fn.ppmt(rate / 12, per, months, principal)
                pmt = fn.pmt(rate / 12, months, principal)
                
                
                
                p = i = 0.00
                if self.method and self.loan_amount and self.term:
                    if np.allclose(ipmt + ppmt, pmt):
                        for payment in per:
                            index = payment - 1
                            principal = principal + ppmt[index]
                            interestpd = np.sum(ipmt)
                            date = datetime.date.today() + relativedelta(months=payment)
                            date = date.replace(day=1)
                            date_list.append((0, 0, {
                                            'due_date': date,
                                            'number': payment,
                                            'saldo_inicial':(ppmt[index] * -1) + abs(principal),
                                            'principal': (ppmt[index] * -1),
                                            'interest': (ipmt[index] * -1),
                                            'interest_rate': str ("%.2f" % ((rate / 12) * 100)) + " %",
                                            'total': (ppmt[index] * -1) + (ipmt[index] * -1),
                                            'balance_amt': abs(principal)
                            }))
            
                        self.cuota = pmt * -1
                            
            if self.method == 'flat':
                if self.loan_amount<=0:
                    raise ValidationError(_('colocar un valor [compuesto] diferente de cero'))
                saldo = self.loan_amount
                principal = self.loan_amount
                rate = self.rate / 100 * principal if self.rate else 0
                time = float(self.term) / 12
                months = self.term
                per = np.arange(months) + 1
                each_month_payment = balance = 0.00
                if time:
                    balance = ((self.loan_amount / time + rate) / 12) * self.term
                    for each_term in per:
                        date = datetime.date.today() + relativedelta(months=each_term)
                        interest = principal / time + rate
                        each_month_payment = interest / 12
                        total_pay_amount = each_month_payment * self.term
                        balance -= each_month_payment
                        monthly_interest = rate * time / self.term
                        monthly_principal = principal / self.term
                        show_rate = self.rate / 12 if self.rate > 0 else 0
                        date_list.append((0, 0, {
                                        'due_date': date,
                                        'number': each_term,
                                        'saldo_inicial': saldo,
                                        'principal': monthly_principal,
                                        'interest': monthly_interest,
                                        'interest_rate': str("%.2f" % show_rate) + " %",
                                        'total': monthly_interest + monthly_principal,
                                        'balance_amt': abs(balance)
                                        }))
                    self.cuota = monthly_interest + monthly_principal 
            self.loan_calc_line_ids = date_list

    loan_amount = fields.Monetary(string="Monto a Financiar")
    principal_amount = fields.Monetary(string="Capital", store=True, readonly=True, compute='_amount_all')
    interest_amount = fields.Monetary(string="Intere", store=True, readonly=True, compute='_amount_all')
    cuota = fields.Monetary(string="cuato", store=True, readonly=True, compute='_amount_all')
    total_amount = fields.Monetary(string="Total", store=True, readonly=True, compute='_amount_all')
    loan_type_id = fields.Many2one('sale.credit.frequency', string="Frecuencia",required=True)
    rate_type = fields.Many2one('sale.credit.category', string="Tipo Tasa",required=True)
    rate = fields.Float("Tasa(%)", related='rate_type.percent_interest', readonly=True)
    installment_id = fields.Many2one('sale.credit.installment', string="Cuotas" , required=True)
    term = fields.Integer("Cuotas", related='installment_id.installments', readonly=True)
    loan_calc_line_ids = fields.One2many('loan.calc.line','loan_calc_id', compute="compute_due_date", string="Loan Type", readonly=False,
                                         store=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.user.company_id, store=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True, store=True)
    method = fields.Selection([
                              ('flat', 'Interes Compueto'),
                              ('reducing', 'Interes Simple')], string="Interes", default='reducing')

    
    @api.onchange('loan_type_id')
    def onchange_loan_type_id(self):
        self.installment_id = False
        
        installments = self.loan_type_id.installment_ids.ids
        return {
            'domain': {
                'installment_id': [
                    ('id', 'in', installments)
                    ]
            }
        }

class loan_calc_line(models.Model):
    _name = 'loan.calc.line'
    _description = 'Loan Calc Line'

    loan_calc_id = fields.Many2one('loan.calc', string="Calculadora Prestamos")
    currency_id = fields.Many2one('res.currency', related='loan_calc_id.currency_id', readonly=True, store=True)
    due_date = fields.Date(string="Fecha de Pago", readonly=True)
    saldo_inicial = fields.Monetary("Saldo Inicial", readonly=True)
    principal = fields.Monetary("Capital", readonly=True)
    interest = fields.Monetary("Interes", readonly=True)
    balance_amt = fields.Monetary("Saldo Final", readonly=True)
    interest_rate = fields.Char("Interes(%)", readonly=True)
    total = fields.Monetary("Cuota", readonly=False)
    method = fields.Selection([('flat', 'Interes Compuesto'), ('reducing', 'Interes Simple')],
                                related="loan_calc_id.method", string="Method", readonly=True)
    number = fields.Integer("No.")
    @api.onchange('total')
    def action_dynamic_quota(self):
        print('listo')
