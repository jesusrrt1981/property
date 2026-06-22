from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SaleCreditLine(models.Model):
    _name = 'sale.credit.line'
    _description = 'Credit Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(
        default=True, help="Set active to false to hide the Account Tag without removing it.")
    is_modified = fields.Boolean(default=False)
    is_modified_comment = fields.Boolean(default=False)
    internal_notes = fields.Text(string="Description")
    amount_capital = fields.Float(string="Importe Capital", digits=(12, 4))
    amount_final = fields.Float(string="Balance", digits=(12, 4))
    amount_fixed = fields.Float(string="Cuota", digits=(12, 4))
    amount_initial = fields.Float(string="Importe Inicial")
    amount_interest_installments = fields.Char("Interes(%)", readonly=True)
    amount_interest = fields.Float(string="Importe Interés", digits=(12, 4))
    amount_others = fields.Float(
        string="Otros (OTROS)",
        digits=(12, 4),
        default=0.0,
        help="Cargos adicionales distribuidos en esta cuota (ej. penalidad de reactivación)."
    )
    amount_paid = fields.Float(string="Remanente", compute = '_compute_amount_paid')
    amount_paid_compute = fields.Float(string="Monto Computado")
    amount_paid_total = fields.Float(string="Monto Pagado")
    amount_residual = fields.Float(string="Monto Pendiente", digits=(12, 4))
    credit_id = fields.Many2one('sale.credit', string='Credito',
                                ondelete="cascade", auto_join=True)
    co_debtor_id = fields.Many2one('res.partner', string='Codeudor')
    company_id = fields.Many2one(
        related='credit_id.company_id', store=True, readonly=True)
    count = fields.Integer(string="Contar")
    last_overdue_date = fields.Date(string="Fecha de Pago Mora")
    currency_id = fields.Many2one(
        related='credit_id.currency_id_money', store=True, readonly=True)
    date_payment = fields.Date(string="Fecha de Pago", compute='_compute_date_payment', store=True)
    expected_date_payment = fields.Date(string="Fecha esperada de Pago")
    has_message = fields.Boolean(string="Has Message")
    journal_id = fields.Many2one('account.journal', string="Diario")
    name = fields.Char(string="Referencia")
    overdue_id = fields.Many2one('credit.overdue', string='Registro de Moras')
    overdue_residual = fields.Float(string="Moras")
    partner_id = fields.Many2one(
        'res.partner', string="Cliente", related='credit_id.partner_id', store=True, readonly=True)
    sale_id = fields.Many2one('sale.order', string="Venta")
    state = fields.Selection([
        ('pending', 'Pagos Pendientes'),
        ('paid_overdue', 'Pago vencido'),
        ('paid_reload', 'pago con recargo'),
        ('paid', 'Pagado'),
        ('cancelled', 'Cancelado'),
        ],
        default='pending',
        string="Estado", tracking=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Almacén")
    # payment_pay_ids = fields.One2many(
    #     comodel_name="account.payment", inverse_name="credit_line_id", string="Pago")
    sale_credit_payment_ids = fields.Many2many(
        'sale.credit.payment', 
        'sale_credit_line_payment_rel', 
        'credit_line_id', 
        'payment_id', 
        string='Pago(s) Vinculado(s)', 
        readonly=True
    )

    pos_payment_ids = fields.Many2many(
        'cjg.pos.payment.receipt',
        'cjg_pos_receipt_credit_line_rel',
        'credit_line_id',
        'receipt_id',
        string='Recibos POS',
        readonly=True,
    )

    
    @api.depends('amount_residual', 'amount_paid_total')
    def _compute_amount_paid(self):
        for record in self:
            record.amount_paid = record.amount_residual - record.amount_paid_total
            
    @api.depends(
        'sale_credit_payment_ids.payment_date',
        'pos_payment_ids.date',
    )
    def _compute_date_payment(self):
        for record in self:
            payment_dates = []
            if record.sale_credit_payment_ids:
                payment_dates.extend(
                    [
                        fields.Date.to_date(payment_date)
                        for payment_date in record.sale_credit_payment_ids.mapped('payment_date')
                        if payment_date
                    ]
                )
            if record.pos_payment_ids:
                payment_dates.extend(
                    [
                        fields.Date.to_date(payment_date)
                        for payment_date in record.pos_payment_ids.mapped('date')
                        if payment_date
                    ]
                )
            record.date_payment = payment_dates and max(payment_dates) or False
            
                   
                    
    def cancel_credit_lines(self):
            for line in self:
                if line.state not in ('paid', 'cancelled'):
                    line.write({
                        'state': 'cancelled',
                        'amount_paid': 0,
                        'amount_residual': 0,
                        'amount_interest': 0,
                        'amount_capital': 0,
                        'amount_fixed': 0,
                    })


    # @api.onchange('expected_date_payment')
    # def valid_date(self):
    #     line_credit = str(self.credit_id.id).replace('NewId_', '')
    #     list_line = self.search(
    #         [('credit_id', '=', int(line_credit)), ('count', '!=', 0)])
    #     if self.count == len(list_line):
    #         raise ValidationError(
    #             _(
    #                 "No puedes cambiar la ultima fecha de la cuota desde la tabla armotizacion"
    #             )
    #         )
    #     fecha_i = self.credit_id.date_start
    #     fecha_f = self.credit_id.date_end

    #     if self.expected_date_payment < fecha_i or self.expected_date_payment == fecha_i:
    #         raise ValidationError(
    #             _(
    #                 "La fecha no  debe ser menor que fecha de inicio"
    #             )
    #         )

    #     elif fecha_f < self.expected_date_payment or self.expected_date_payment == fecha_f:

    #         raise ValidationError(
    #             _(
    #                 "La fecha no debe ser mayor que fecha final"
    #             )
    #         )

    @api.onchange('amount_fixed')
    def action_dynamic_quota(self):
        line_credit = str(self.credit_id.id).replace('NewId_', '')
        list_line = self.search(
            [('credit_id', '=', int(line_credit)), ('count', '!=', 0)])
        valid_total_sold = []
        valid_amount_financed = []
        acumulate = 0
        if self.amount_fixed == 0:
            raise ValidationError(
                _(
                    "Por favor, no colocar una cuota en valor 0"
                )
            )

        if self.amount_interest != 0 and self.amount_fixed != 0:
            for record in list_line:

                if record.count == self.count:

                    if len(list_line) == self.count:
                        new_line = len(list_line)
                    else:
                        new_line = int(record.count) + 1
                    next_line = record.search(
                        [('count', '=', new_line), ('credit_id', '=', int(line_credit))])

                    if record.amount_residual < record.amount_fixed:
                        remaining_quantity = self.amount_fixed - self.amount_residual
                        new_cuota = next_line.amount_fixed + remaining_quantity
                        interest = self.amount_fixed - self.amount_capital
                        balance = self.amount_initial - new_cuota
                        op_amount_Capital = self.amount_fixed - record.amount_fixed
                        amount_capital = self.amount_capital + op_amount_Capital

                    else:
                        remaining_quantity = self.amount_residual - self.amount_fixed
                        new_cuota = next_line.amount_fixed + remaining_quantity
                        op_amount_Capital = self.amount_fixed - record.amount_fixed
                        amount_capital = self.amount_capital + op_amount_Capital
                        balance = self.amount_initial - self.amount_fixed
                        op_interest = next_line.amount_fixed - next_line.amount_capital
                        interest = op_interest

                    record.write({'amount_capital': amount_capital, 'amount_final': balance,
                                 'amount_residual': self.amount_fixed, 'amount_interest': self.amount_interest})
                    balance_f = balance - new_cuota

                    next_line.write({'amount_initial': balance, 'amount_capital': new_cuota - next_line.amount_interest,
                                    'amount_fixed': new_cuota, 'amount_final': balance_f, 'amount_residual': new_cuota, 'amount_interest': interest})

                valid_amount_financed.append(record.amount_capital)
                valid_total_sold.append(record.amount_residual)

            total_sold = self.credit_id.total_sold
            financed = self.credit_id.amount_financed
            amount_interest_value = self.credit_id.amount_interest_value
            validation_interest_value = amount_interest_value + total_sold

            if self.credit_id.state == 'draft':
                if total_sold != round(sum(valid_total_sold), 2) and financed != round(sum(valid_amount_financed), 2):
                    raise ValidationError(
                        _(
                            f"No se puede financiar mas del precio original del producto {round(validation_interest_value,2)}"
                        )
                    )
        else:
            for record in list_line:

                if record.count == self.count:

                    if len(list_line) == self.count:
                        new_line = len(list_line)
                    else:
                        new_line = int(record.count) + 1
                    next_line = record.search(
                        [('count', '=', new_line), ('credit_id', '=', int(line_credit))])
                    if record.amount_residual < record.amount_fixed:
                        remaining_quantity = self.amount_fixed - self.amount_residual
                        new_cuota = next_line.amount_fixed + remaining_quantity
                        balance = self.amount_initial - new_cuota

                    else:
                        remaining_quantity = self.amount_residual - self.amount_fixed
                        new_cuota = next_line.amount_fixed + remaining_quantity
                        balance = self.amount_initial - self.amount_fixed
                    record.write({'amount_capital': self.amount_fixed,
                                 'amount_final': balance, 'amount_residual': self.amount_fixed})
                    balance_f = balance - new_cuota
                    next_line.write({'amount_initial': balance, 'amount_capital': new_cuota,
                                    'amount_fixed': new_cuota, 'amount_final': balance_f, 'amount_residual': new_cuota})

                valid_amount_financed.append(record.amount_capital)
                valid_total_sold.append(record.amount_residual)

            total_sold = round(self.credit_id.total_sold, 2)
            financed = round(self.credit_id.amount_financed, 2)

            if self.credit_id.state == 'draft':
                if total_sold != round(sum(valid_total_sold), 2) and financed != round(sum(valid_amount_financed), 2):

                    raise ValidationError(
                        _(
                            f"No se puede financiar mas del precio original del producto {total_sold}  aunque {financed}"
                        )
                    )


    def action_view_planilla(self):
        """Smart button para ver la planilla origen"""
        self.ensure_one()
        if not self.crm_lead_id:
            return
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Planilla CRM',
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.crm_lead_id.id,
            'target': 'current',
        }

    def action_view_credit_overdues(self):
        pass
