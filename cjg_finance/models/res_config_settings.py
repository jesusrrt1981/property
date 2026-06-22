from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):

    _inherit = 'res.config.settings'

    credit_flow = fields.Selection(
        related='company_id.credit_flow',
        readonly=False,
        string="Flujo de Crédito",
    )

    overdue_type_credit = fields.Selection(
        related='company_id.overdue_type_credit',
        readonly=False,
        string="Tipo de Mora de Crédito",
    )

    importe = fields.Float(string="Importe de mora",related='company_id.importe',readonly=False,)
    
    porcentaje = fields.Float(string="Porcentaje de mora %",related='company_id.porcentaje',readonly=False,)

    overdue_type = fields.Selection(
        related='company_id.overdue_type',
        readonly=False,
        string="Tipo de Mora",
    )

    overdue_type_apply = fields.Selection(
        readonly=False,
        related='company_id.overdue_type_apply',
        string="Flujo de aplicacion de mora",
    )
    @api.onchange('overdue_type_apply')
    def _manual_apply(self):
        for record in self:
            if record.overdue_type_apply!='manual':
                sale_credit=record.env['sale.credit'].search([])
                for credit in sale_credit:
                    credit.write({'config_general':True})
            else: 
                sale_credit=record.env['sale.credit'].search([])
                for credit in sale_credit:
                    credit.write({'config_general':False})


    credit_cron_limit = fields.Char(
        'Límite del Cron de Crédito',
        related='company_id.credit_cron_limit',
        readonly=False,
    )

    payment_cron_limit = fields.Char(
        'Límite del Cron de Pago',
        related='company_id.credit_cron_limit',
        readonly=False,
    )

    split_credit_process = fields.Boolean(
        string="Dividir Proceso de Crédito",
        related='company_id.split_credit_process',
        readonly=False,
    )

    credit_overdue = fields.Float(
        string="Moras de Crédito", related='company_id.credit_overdue', readonly=False
    )
    manager_ids = fields.Many2many(
        string='Gerentes de Crédito',
        comodel_name='res.users',
        related='company_id.manager_ids',
        readonly=False,
    )

    overdue_allowed_amount = fields.Float(
        string="Deuda mayor a",
        related='company_id.overdue_allowed_amount',
        readonly=False,
    )
    overdue_invoice_limit = fields.Integer(
        string="Límite Máximo de Moras",
        related='company_id.overdue_invoice_limit',
        readonly=False,
    )


    overdue_period = fields.Selection(
        string="Frecuencia de Moras",
        related='company_id.overdue_period',
        readonly=False,
    )

    payment_mail = fields.Char(
        'Email de Pago', related='company_id.payment_mail', readonly=False
    )
    payment_phone = fields.Char('Teléfono de Pago')

    product_interest = fields.Many2one(
        'product.product',
        string="Interés del Producto",
        related='company_id.product_interest',
        readonly=False,
    )
    product_overdue = fields.Many2one(
        'product.product',
        string="Mora del Producto",
        related='company_id.product_overdue',
        readonly=False,
    )

    term_and_conditions = fields.Html(
        'Términos y Condiciones del Crédito',
        related='company_id.term_and_conditions',
        readonly=False,
    )
    
    credit_journal_id = fields.Many2one(
        related='company_id.credit_journal_id',
        string="Diario Prestamos",
        readonly=False,)
    
    credit_account_receivable_id = fields.Many2one(
        related='company_id.credit_account_receivable_id',
        readonly=False,)

    credit_account_advanced_id = fields.Many2one(
        related='company_id.credit_account_advanced_id',
        readonly=False,)

    credit_earning_id = fields.Many2one(
        related='company_id.credit_earning_id',
        readonly=False,)

    # ============================================
    # REFINANCING CONFIGURATION FIELDS
    # ============================================
    
    refinance_min_capital_down_pct = fields.Float(
        string="Abono Mínimo a Capital (%)",
        config_parameter='cjg_finance.refinance_min_capital_down_pct',
        default=10.0,
        help="Porcentaje mínimo del saldo que debe abonarse al capital para poder refinanciar. "
             "Ejemplo: 10% significa que si el saldo es $10,000, el abono mínimo debe ser $1,000"
    )
    
    refinance_allow_shorter_term = fields.Boolean(
        string="Permitir Plazo Menor en Refinanciamiento",
        config_parameter='cjg_finance.refinance_allow_shorter_term',
        default=False,
        help="Si está marcado, permite refinanciar reduciendo el número de cuotas pendientes. "
             "Si no está marcado, el nuevo plazo debe ser igual o mayor al actual"
    )
    
    refinance_penalty_rate = fields.Float(
        string="Penalización por Refinanciamiento (%)",
        config_parameter='cjg_finance.refinance_penalty_rate',
        default=2.0,
        help="Porcentaje del saldo actual que se cobra como penalización al refinanciar. "
             "Este monto se suma al nuevo saldo a financiar"
    )
    
    refinance_allow_with_overdue = fields.Boolean(
        string="Permitir Refinanciar con Saldo Vencido",
        config_parameter='cjg_finance.refinance_allow_with_overdue',
        default=False,
        help="Si está marcado, permite refinanciar créditos que tienen cuotas vencidas. "
             "Si no está marcado, el cliente debe estar al día para refinanciar"
    )
    
    refinance_min_term_no_interest = fields.Integer(
        string="Plazo Mínimo Sin Intereses Adicionales (meses)",
        config_parameter='cjg_finance.refinance_min_term_no_interest',
        default=3,
        help="Si el nuevo plazo es menor o igual a este valor, no se cobran intereses adicionales. "
             "Útil para refinanciamientos a corto plazo"
    )