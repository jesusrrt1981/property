from odoo import fields, models,api
from odoo.exceptions import ValidationError
class SaleCreditCancelWizard(models.TransientModel):
    _name = 'sale.credit.exoneracion.wizard'
    _description = 'Cancelación de solicitud de credito'


    reason_cancellation = fields.Text(string='Descripcion', required=True)
    # sale_order_ids = fields.Many2many(
    #     'sale.credit', default=lambda self: self.env.context.get('active_ids'))
    credit_line_id = fields.Many2one('sale.credit.line', string='Credito', domain="[('credit_id', '=', credit_id)]")

    advance_payment_method = fields.Selection(
        selection=[
            ('delivered', "Exoneracion completa"),
            ('percentage', "Exoneracion por porcentaje"),
            ('fixed', "Exoneracion por monto fijo"),
        ],
        string="Create Invoice",
        default='delivered',
        required=True,
        help="A standard invoice is issued with all the order lines ready for invoicing,"
            "according to their invoicing policy (based on ordered or delivered quantity).")
    amount = fields.Float(
        string="Monto de exoneracion",
        help="The percentage of amount to be invoiced in advance, taxes excluded.")
    amount_percent = fields.Float(
        string="Porcentaje de exoneracion",
        help="The percentage of amount to be invoiced in advance, taxes excluded.")

    current_overdue_amount = fields.Float(string="Monto de mora actual", compute="_compute_amounts")
    projected_overdue_amount = fields.Float(string="Monto de mora proyectado", compute="_compute_amounts")

    @api.depends('credit_line_id', 'advance_payment_method', 'amount', 'amount_percent')
    def _compute_amounts(self):
       
        overdue_model = self.env['credit.overdue']
        active_id = self._context.get('active_id')
        overdue_record = overdue_model.browse(active_id)
        credit_line = overdue_record.credit_line_id
        overdue_record.debt_overdue = credit_line.overdue_residual

        for record in self:
            record.current_overdue_amount = record.credit_line_id.overdue_residual
            if record.advance_payment_method == 'delivered':
                waived_amount = abs(credit_line.overdue_residual)
            elif record.advance_payment_method == 'percentage':
                waived_amount = credit_line.overdue_residual * (record.amount_percent / 100)
            elif record.advance_payment_method == 'fixed':
                waived_amount = record.amount
            else:
                waived_amount = 0
            record.current_overdue_amount = credit_line.overdue_residual
            record.projected_overdue_amount = credit_line.overdue_residual - waived_amount

    def action_confirm(self):
        overdue_model = self.env['credit.overdue']
        active_id = self._context.get('active_id')
        overdue_record = overdue_model.browse(active_id)
        credit_line = overdue_record.credit_line_id
        overdue_residual = abs(credit_line.overdue_residual)
        today = fields.Date.today()


        if self.advance_payment_method == 'delivered': 
            waived_amount = overdue_residual
        elif self.advance_payment_method == 'percentage': 
            if self.amount_percent > 100:
                raise ValidationError("El porcentaje no puede ser mayor a 100.")
            waived_amount = overdue_residual * (self.amount_percent / 100)
        elif self.advance_payment_method == 'fixed':
            if self.amount > overdue_residual:
                raise ValidationError("El monto no puede ser mayor al monto de la mora.")
            waived_amount = self.amount

        if waived_amount and self.advance_payment_method == 'delivered' :
            credit_line.write({
                "overdue_residual": -waived_amount,
                "amount_residual": credit_line.amount_residual - waived_amount,
            })  
            
            error_message = f"""
            <p><span style="font-weight: bold; color: #0012e8;">Mora Exonerada Completamente</span></p> 
            <p><span style="font-weight: bold;">Linea de credito:</span> {credit_line.name}</p>
            <p><span style="font-weight: bold;">Realizado por:</span> {self.env.user.name}</p>
            <p><span style="font-weight: bold;">Razon de exoneración:</span> {self.reason_cancellation}</p>
            <p><span style="font-weight: bold;">En Fecha:</span> {today}</p> 
            <p><span style="font-weight: bold;">Cantidad exonerada:</span> {waived_amount} {credit_line.credit_id.currency_id_money.name}</p>
            <p><span style="font-weight: bold;">Mora restante:</span> {credit_line.overdue_residual} {credit_line.credit_id.currency_id_money.name}</p>"""
            credit_line.credit_id.message_post(body=error_message)

            overdue_record.write({
                'state': 'exonerated',
                'is_exonerated': True,
                'debt_overdue': -waived_amount
            })

            overdue_history = self.env['credit.overdue.history'].create({
                'name': credit_line.name or "Referencia",
                'company_id': self.env.company.id,
                'user_id': self.env.user.id,
                'overdue_date': fields.Date.today(),
                'previous_overdue_amount': credit_line.overdue_residual,
                'new_overdue_amount': credit_line.overdue_residual - waived_amount,
                'overdue_amount': waived_amount,
                'credit_line_id': credit_line.id,
                'state': 'exonerated',
            })
        

        elif waived_amount and self.advance_payment_method == 'percentage' :
            credit_line.write({
                "overdue_residual": credit_line.overdue_residual - waived_amount,
                "amount_residual": credit_line.amount_residual - waived_amount,
            })  
            overdue_record.write({
                'state': 'exonerated_percent',
                'exonerated_percent': True,
                'debt_overdue': credit_line.overdue_residual
            })

            error_message = f"""
            <p><span style="font-weight: bold; color: #0012e8;">Mora Exonerada por porcentaje</span></p> 
            <p><span style="font-weight: bold;">Linea de credito:</span> {credit_line.name}</p>
            <p><span style="font-weight: bold;">Realizado por:</span> {self.env.user.name}</p>
            <p><span style="font-weight: bold;">Razon de exoneración:</span> {self.reason_cancellation}</p>
            <p><span style="font-weight: bold;">En Fecha:</span> {today}</p> 
            <p><span style="font-weight: bold;">Cantidad exonerada:</span> {waived_amount} {credit_line.credit_id.currency_id_money.name}</p>
            <p><span style="font-weight: bold;">Mora restante:</span> {credit_line.overdue_residual} {credit_line.credit_id.currency_id_money.name}</p>"""
            credit_line.credit_id.message_post(body=error_message)


            overdue_history = self.env['credit.overdue.history'].create({
                'name': credit_line.name or "Referencia",
                'company_id': self.env.company.id,
                'user_id': self.env.user.id,
                'overdue_date': fields.Date.today(),
                'previous_overdue_amount': credit_line.overdue_residual,
                'new_overdue_amount': credit_line.overdue_residual - waived_amount,
                'overdue_amount': waived_amount,
                'credit_line_id': credit_line.id,
                'state': 'exonerated_percent',
            })
           
        

        
        elif waived_amount and self.advance_payment_method == 'fixed' :
            credit_line.write({
                "overdue_residual": credit_line.overdue_residual - waived_amount,
                "amount_residual": credit_line.amount_residual - waived_amount,
            })  
            overdue_record.write({
                'state': 'exonerated_amount',
                'exonerated_amount': True,
                'debt_overdue': credit_line.overdue_residual
            })

            error_message = f"""
            <p><span style="font-weight: bold; color: #0012e8;">Mora Exonerada por monto fijo</span></p> 
            <p><span style="font-weight: bold;">Linea de credito:</span> {credit_line.name}</p>
            <p><span style="font-weight: bold;">Realizado por:</span> {self.env.user.name}</p>
            <p><span style="font-weight: bold;">Razon de exoneración:</span> {self.reason_cancellation}</p>
            <p><span style="font-weight: bold;">En Fecha:</span> {today}</p> 
            <p><span style="font-weight: bold;">Cantidad exonerada:</span> {waived_amount} {credit_line.credit_id.currency_id_money.name}</p>
            <p><span style="font-weight: bold;">Mora restante:</span> {credit_line.overdue_residual} {credit_line.credit_id.currency_id_money.name}</p>"""
            credit_line.credit_id.message_post(body=error_message)

            overdue_history = self.env['credit.overdue.history'].create({
                'name': credit_line.name or "Referencia",
                'company_id': self.env.company.id,
                'user_id': self.env.user.id,
                'overdue_date': fields.Date.today(),
                'previous_overdue_amount': waived_amount + credit_line.overdue_residual,
                'new_overdue_amount': credit_line.overdue_residual,
                'overdue_amount': waived_amount,
                'credit_line_id': credit_line.id,
                'state': 'exonerated_amount',
            })
            
        return {'type': 'ir.actions.act_window_close'}