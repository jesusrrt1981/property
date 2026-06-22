from odoo import models, fields, api, _


class SaleCreditPaymentLine(models.Model):
    _name = 'sale.credit.payment.line'
    _description = 'Credit Payment Line'

    # payment_ids = fields.One2many(comodel_name="account.payment", inverse_name="credit_line_id", string="Pago")
    state = fields.Selection(string="Estado", selection=[
        ('pending', 'Por Pagar'),
        ('paid_overdue','Pago vencido'),
        ('paid_reload','pago con recargo'),
        ('paid', 'Pagado'),
        ('cancelled', 'Cancelado'),], default='pending')
    company_id = fields.Many2one('res.company', related='sale_payment_id.company_id', store=True, readonly=True)
    is_paid = fields.Boolean(string="Esta Pagado" , default=False)
    amount_paid = fields.Float(string="Total Pagado", digits=(16, 2))
    amount_capital = fields.Float(string="Importe Capital", digits=(16, 2))
    amount_final = fields.Float(string="Importe Final", digits=(16, 2))
    amount_fixed = fields.Float(string="Importe Fijo", digits=(16, 2))
    amount_initial = fields.Float(string="Importe Inicial", digits=(16, 2))
    amount_interest = fields.Float(string="Importe Interés", digits=(16, 2))
    amount_overdue = fields.Float(string="Importe Moras", digits=(16, 2))
    amount_payable = fields.Float(string="Importe a Pagar", digits=(16, 2))
    co_debtor_id = fields.Many2one('res.partner', string='Codeudor')
    count = fields.Integer(string="Contar")
    credit_line_id = fields.Many2one(
        'sale.credit.line', string='Línea de Crédito')
    sale_payment_id = fields.Many2one(
        'sale.credit.payment', string='Pago Credito', ondelete="cascade", auto_join=True)
    currency_id = fields.Many2one(
        related='sale_payment_id.currency_id', store=True, readonly=True)
    expected_date_payment = fields.Date(string="Fecha esperada de Pago")
    partner_id = fields.Many2one('res.partner', string="Cliente")
    payable = fields.Selection([
        ('full', 'Completo'),
        ('partial', 'Parcial'),
        ('not', 'NO')],
        string="Pagable", compute="_compute_payable", store=True)
    remanente = fields.Float(string="Remanente", digits=(16, 2))
    overdue_id = fields.Many2one('credit.overdue', string='Moras')
    preview_amount_paid = fields.Float(string="Total Pagado (Vista previa)", digits=(16, 2))
    preview_remanente = fields.Float(string="Remanente (Vista previa)", digits=(16, 2))
    preview_amount_overdue = fields.Float(string="Importe Moras (Vista previa)", digits=(16, 2))
    preview_state = fields.Selection(string="Estado (Vista previa)", selection=[
        ('pending', 'Por Pagar'),
        ('paid_overdue','Pago vencido'),
        ('paid_reload','pago con recargo'),
        ('paid', 'Pagado'), ], default='pending')

    @api.depends('amount_payable', 'amount_paid')
    def _compute_payable(self):
        for rec in self:
            state = "not"
            if rec.amount_paid > 0:
                result = rec.amount_payable - rec.amount_paid
                if result == 0:
                    state = "full"
                else:
                    state = "partial"
            rec.payable = state
                
    def cancel_payment_lines(self):
        for line in self:
            if line.state not in ('paid', 'cancelled'):
                line.write({
                    'state': 'cancelled',
                    'amount_paid': 0,
                    'remanente': 0,
                    'amount_overdue': 0,
                })
