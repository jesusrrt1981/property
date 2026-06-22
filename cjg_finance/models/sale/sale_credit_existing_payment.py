from odoo import models, fields, api

class SaleCreditExistingPayment(models.Model):
    _name = 'sale.credit.existing.payment'
    _description = 'Pagos Existentes Temporales para Refinanciamiento'
    
    active = fields.Boolean(default=True)
    credit_id = fields.Many2one('sale.credit', string="Crédito")
    count = fields.Integer(string="Número de Cuota")
    amount_paid = fields.Float(string="Monto Pagado")
    remanente = fields.Float(string="Remanente")
    date_payment = fields.Date(string="Fecha de Pago", compute='_compute_date_payment', store=True)
    # payment_ids = fields.Many2many('account.payment', string="Pagos Asociados")
    sale_credit_payment_ids = fields.Many2many(
        'sale.credit.payment', 
        'sale_credit_existing_payment_rel', 
        'existing_payment_id', 
        'sale_credit_payment_id', 
        string='Pago(s) Vinculado(s)', 
        readonly=True
    )
    credit_line_id = fields.Many2one('sale.credit.line', string='Línea de Crédito')

    @api.depends('sale_credit_payment_ids', 'sale_credit_payment_ids.payment_date')
    def _compute_date_payment(self):
        for record in self:
            if record.sale_credit_payment_ids:
                record.date_payment = max(record.sale_credit_payment_ids.mapped('payment_date'))
            else:
                record.date_payment = False