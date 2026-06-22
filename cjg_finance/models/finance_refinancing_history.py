from odoo import api, fields, models, _

class FinanceRefinancingHistory(models.Model):
    _name = 'finance.refinancing.history'
    _description = 'Histórico de Refinanciamientos'
    _order = 'refinance_date desc, id desc'
    _rec_name = 'display_name'
    
    # ============================================
    # RELACIONES
    # ============================================
    
    credit_id = fields.Many2one(
        'sale.credit', 
        string='Crédito', 
        required=True, 
        ondelete='cascade',
        index=True,
        help="Crédito que fue refinanciado"
    )
    partner_id = fields.Many2one(
        'res.partner', 
        string='Cliente', 
        related='credit_id.partner_id', 
        store=True,
        help="Cliente del crédito"
    )
    
    # ============================================
    # DATOS TEMPORALES
    # ============================================
    
    refinance_date = fields.Datetime(
        string='Fecha Refinanciamiento', 
        default=fields.Datetime.now, 
        required=True,
        help="Fecha y hora en que se realizó el refinanciamiento"
    )
    user_id = fields.Many2one(
        'res.users', 
        string='Usuario', 
        default=lambda self: self.env.user, 
        required=True,
        help="Usuario que ejecutó el refinanciamiento"
    )
    
    # ============================================
    # ESTADO ANTERIOR (Before refinancing)
    # ============================================
    
    old_balance = fields.Monetary(
        string='Saldo Anterior', 
        currency_field='currency_id',
        help="Saldo total antes del refinanciamiento"
    )
    old_installments_pending = fields.Integer(
        string='Cuotas Pendientes Anteriores',
        help="Número de cuotas que quedaban por pagar"
    )
    old_installment_value = fields.Monetary(
        string='Valor Cuota Anterior', 
        currency_field='currency_id',
        help="Valor de la cuota mensual antes del refinanciamiento"
    )
    old_interest_rate = fields.Float(
        string='Tasa Anterior (%)',
        digits=(5, 2),
        help="Tasa de interés anual antes del refinanciamiento"
    )
    
    # ============================================
    # PARÁMETROS DEL REFINANCIAMIENTO
    # ============================================
    
    capital_down_payment = fields.Monetary(
        string='Abono a Capital', 
        currency_field='currency_id',
        help="Monto abonado al capital al momento del refinanciamiento"
    )
    penalty_applied = fields.Monetary(
        string='Penalización Aplicada', 
        currency_field='currency_id',
        help="Monto de penalización por refinanciar (% del saldo)"
    )
    new_interest_generated = fields.Monetary(
        string='Interés Generado', 
        currency_field='currency_id',
        help="Nuevos intereses generados por el refinanciamiento"
    )
    
    # ============================================
    # ESTADO NUEVO (After refinancing)
    # ============================================
    
    new_balance = fields.Monetary(
        string='Nuevo Saldo', 
        currency_field='currency_id',
        help="Saldo total después del refinanciamiento (capital + penalización + intereses)"
    )
    new_installments = fields.Integer(
        string='Nuevas Cuotas',
        help="Número de cuotas del nuevo plan de pagos"
    )
    new_installment_value = fields.Monetary(
        string='Nuevo Valor Cuota', 
        currency_field='currency_id',
        help="Valor de la nueva cuota mensual"
    )
    new_interest_rate = fields.Float(
        string='Nueva Tasa (%)',
        digits=(5, 2),
        help="Tasa de interés anual después del refinanciamiento"
    )
    
    # ============================================
    # OTROS
    # ============================================
    
    currency_id = fields.Many2one(
        'res.currency', 
        related='credit_id.currency_id', 
        store=True,
        string="Moneda"
    )
    
    notes = fields.Text(
        string='Notas',
        help="Notas u observaciones sobre este refinanciamiento"
    )
    
    display_name = fields.Char(
        string='Nombre', 
        compute='_compute_display_name', 
        store=True
    )
    
    # ============================================
    # MÉTODOS COMPUTED
    # ============================================
    
    line_ids = fields.One2many(
        'finance.refinancing.line', 'history_id', string='Detalle de Cuotas'
    )
    
    @api.depends('credit_id.name', 'refinance_date')
    def _compute_display_name(self):
        for record in self:
            if record.credit_id and record.refinance_date:
                record.display_name = _('Refinanciamiento %s - %s') % (
                    record.credit_id.name,
                    fields.Datetime.to_string(record.refinance_date)[:10]
                )
            else:
                record.display_name = _('Nuevo Refinanciamiento')


class FinanceRefinancingLine(models.Model):
    _name = 'finance.refinancing.line'
    _description = 'Línea de Histórico de Refinanciamiento'
    _order = 'date_maturity asc, id asc'

    history_id = fields.Many2one('finance.refinancing.history', string='Refinanciamiento', ondelete='cascade')
    
    number = fields.Char(string='Nro', help="Ej: 01/60")
    date_maturity = fields.Date(string='Vence')
    description = fields.Char(string='Descripción')
    amount_quota = fields.Monetary(string='Monto Cuota', currency_field='currency_id')
    
    # Pagos asociados
    payment_ref = fields.Char(string='Recibo')
    payment_date = fields.Date(string='Fecha Pago')
    
    paid_capital = fields.Monetary(string='Capital Pagado', currency_field='currency_id')
    paid_interest = fields.Monetary(string='Interés Pagado', currency_field='currency_id')
    paid_others = fields.Monetary(string='Otros', currency_field='currency_id')
    paid_total = fields.Monetary(string='Total Pagado', currency_field='currency_id')
    
    balance = fields.Monetary(string='Saldo', currency_field='currency_id')
    
    currency_id = fields.Many2one('res.currency', related='history_id.currency_id', store=True)
