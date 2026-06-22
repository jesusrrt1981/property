from odoo import fields, models,api
import datetime
from datetime import timedelta
import numpy as np
from dateutil.relativedelta import relativedelta
import numpy_financial as fn
from odoo.exceptions import ValidationError
class SaleCreditCancelWizard(models.TransientModel):
    _name = 'sale.credit.personalizacion.wizard'
    _description = 'Cancelación de solicitud de credito'

    line_percentage = fields.Float(string="Porcentaje de Línea", compute="_compute_line_percentage", readonly=True)
    reason_cancellation = fields.Text(string='Descripcion', required=False)
    sale_order_ids = fields.Many2many(
        'sale.credit', default=lambda self: self.env.context.get('active_ids'))
    sale_credit_line=fields.Many2one(
        'sale.credit.line',string='Linea de cuota', domain="[('credit_id', '=', sale_order_ids),('count','!=',0)]")
    
    amount = fields.Float(
        string="Monto",
        help="The percentage of amount to be invoiced in advance, taxes excluded.")
    
    amount_percent = fields.Float(
        string="Porcentaje",
        help="The percentage of amount to be invoiced in advance, taxes excluded.")
    
    date_payment = fields.Date(string="Fecha de modificacion")
        
    modify_type = fields.Selection(
        [('amount', 'Monto'), ('percentage', 'Porcentaje')],
        string="Tipo de Modificación",
        default='amount'
    )

    current_amount = fields.Float(string="Cuota Actual", compute="_compute_current_amount")
    
    modified_amount = fields.Float(string="Cuota Modificada", compute="_compute_modified_amount")
    

    @api.depends('sale_credit_line', 'sale_credit_line.amount_fixed')
    def _compute_line_percentage(self):
        for record in self:
            if record.sale_credit_line:
                total_loan = self.env['sale.credit'].browse(record.sale_credit_line.credit_id.id).credit_Adeudado
                if total_loan:
                    record.line_percentage = (record.sale_credit_line.amount_fixed / total_loan) * 100
                else:
                    record.line_percentage = 0.0
            else:
                record.line_percentage = 0.0
    
    @api.depends("sale_credit_line")
    def _compute_current_amount(self):
        for record in self:
            record.current_amount = record.sale_credit_line.amount_fixed
            self.date_payment = record.sale_credit_line.expected_date_payment
    
    @api.depends("amount_percent", "amount")
    def _compute_modified_amount(self):
        for record in self:
            if record.amount_percent:
                total_loan = self.env['sale.credit'].browse(record.sale_credit_line.credit_id.id).credit_Adeudado
                record.modified_amount = total_loan * (record.amount_percent / 100)
            else:
                record.modified_amount = record.amount
                
    def _add_to_log(self, credit_record, message):
        now = fields.Datetime.now()
        
        user = self.env.user.name
        
        log_entry = f"{now.strftime('%Y-%m-%d %H:%M:%S')} - {user} - {message}\n"

        credit_record.error_log = (credit_record.error_log or '') + log_entry

    def action_confirm(self):
        
        if not self.sale_credit_line:
            raise ValidationError('Debe seleccionar una línea de cuota para continuar.')

        total_loan = self.env['sale.credit'].browse(self.sale_credit_line.credit_id.id).credit_Adeudado

        
        if self.modify_type == 'amount' and self.amount <= 0:
            raise ValidationError('El monto introducido debe ser mayor a 0.')
        
        if self.modify_type == 'percentage' and self.amount_percent <= 0:
            raise ValidationError('El porcentaje introducido debe ser mayor a 0%.')
        
        line_0 = self.env['sale.credit.line'].search([
            ('credit_id', '=', self.sale_credit_line.credit_id.id),
            ('count', '=', 0)], limit=1)
        line_0_percentage = round((line_0.amount_fixed / total_loan) * 100) if total_loan else 0

        modified_lines = self.env['sale.credit.line'].search([
            ('credit_id', '=', self.sale_credit_line.credit_id.id),
            ('id', '!=', self.sale_credit_line.id),
            ('id', '!=', line_0.id),
            ('is_modified', '=', True)], order='count')
            
        already_assigned_percentage = sum(round((line.amount_fixed / total_loan) * 100) for line in modified_lines)

        if self.modify_type == 'percentage':
            if self.amount_percent > 100:
                raise ValidationError('El porcentaje introducido no puede exceder el 100%.')

            total_percentage = already_assigned_percentage + self.amount_percent + line_0_percentage

            if total_percentage > 100:
                raise ValidationError(
                    f'El porcentaje total excede el 100%. Reduce el porcentaje introducido.'
                )

            self.amount = total_loan * (self.amount_percent / 100)
            
            if not self.sale_credit_line.internal_notes:
                self.sale_credit_line.internal_notes = f"{self.amount_percent}% del total"
            
            if not line_0.internal_notes:
                line_0.internal_notes =f"{line_0_percentage}% del total"

            MARGIN_ERROR = 0.05

            difference = abs((self.amount + sum(line.amount_fixed for line in modified_lines) + line_0.amount_fixed) - total_loan)

            if already_assigned_percentage + self.amount_percent + line_0_percentage > 99.5:
                if difference > MARGIN_ERROR:
                    raise ValidationError('La suma de las cuotas modificadas y la línea 0 no puede exceder el total del préstamo.')
            else:
                if (self.amount + sum(line.amount_fixed for line in modified_lines) + line_0.amount_fixed) > total_loan:
                    raise ValidationError('La suma de las cuotas modificadas y la línea 0 no puede exceder el total del préstamo.')

        else:
            if not self.sale_credit_line.internal_notes:
                self.sale_credit_line.internal_notes = self.reason_cancellation

        capital_ratio = self.sale_credit_line.amount_capital / self.sale_credit_line.amount_fixed
        interest_ratio = self.sale_credit_line.amount_interest / self.sale_credit_line.amount_fixed
        
        self.sale_credit_line.internal_notes = self.reason_cancellation
        self.sale_credit_line.amount_fixed = self.amount
        self.sale_credit_line.amount_capital = self.amount * capital_ratio
        self.sale_credit_line.amount_interest = self.amount * interest_ratio
        self.sale_credit_line.expected_date_payment = self.date_payment or self.sale_credit_line.expected_date_payment
        self.sale_credit_line.is_modified = True
        self.sale_credit_line.amount_residual = self.sale_credit_line.amount_capital + self.sale_credit_line.amount_interest

        unmodified_lines = self.env['sale.credit.line'].search([
            ('credit_id', '=', self.sale_credit_line.credit_id.id),
            ('id', '!=', self.sale_credit_line.id),
            ('id', '!=', line_0.id),
            ('is_modified', '=', False)], order='count')

        remaining_amount = total_loan - self.amount - sum(line.amount_fixed for line in modified_lines) - line_0.amount_fixed
        new_unmodified_line_amount = remaining_amount / len(unmodified_lines)

        for line in unmodified_lines:
            capital_ratio = line.amount_capital / line.amount_fixed
            interest_ratio = line.amount_interest / line.amount_fixed

            line.amount_fixed = max(new_unmodified_line_amount, 0)
            line.amount_capital = line.amount_fixed * capital_ratio
            line.amount_interest = line.amount_fixed * interest_ratio
            line.amount_residual = line.amount_capital + line.amount_interest
        
        message_modify_type = ""
        
        if  self.modify_type == 'amount':
            message_modify_type = "Monto"
            
        else:
            message_modify_type = "Porcentaje"
            
        message = f"La línea {self.sale_credit_line.count} ha sido modificada. Nuevo monto: {self.amount}. Tipo de modificación: Por {message_modify_type}. Descripcion: {self.sale_credit_line.internal_notes} Fecha: {self.sale_credit_line.expected_date_payment}"
        
        self._add_to_log(self.sale_credit_line.credit_id, message)
