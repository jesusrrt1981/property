import logging

from odoo import models, fields, api, _
import numpy as np
import datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)
import numpy_financial as fn
from odoo.exceptions import ValidationError, UserError


class SaleCredit(models.Model):
    _name = 'sale.credit'
    _description = 'Sale Credit'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']

    # Máquina de estados explícita (H-C07).
    # Cada estado declara a cuáles puede transicionar.
    # El método write() valida cualquier cambio que toque state.
    #
    # Estados terminales del flujo de devolución/mejora (Proceso Reactivación y Mejora):
    # - anulado_devolucion: contrato cancelado por reembolso 70/30 o transferencia.
    # - desistido_devolucion: contrato desistido por reembolso 70/30 o transferencia.
    # - anulado_mejora: contrato cancelado por mejora de producto (legacy id_status).
    # - activo_reactivado: estado del NUEVO contrato reactivado con precio nuevo
    #   (legacy estatus 39). El contrato viejo queda en anulado_mejora (terminal).
    #   El nuevo contrato apunta al viejo via process_origin_credit_id / origin_credit_id.
    _ALLOWED_STATE_TRANSITIONS = {
        'draft':       {'requested', 'cancelled', 'refuse'},
        'requested':   {'pending', 'approved', 'refuse', 'cancelled'},
        'pending':     {'verified', 'approved', 'refuse'},
        'verified':    {'approved', 'resent', 'refuse'},
        'resent':      {'approved', 'refuse'},
        'approved':    {'active', 'withdrawing', 'cancelled', 'closed', 'forgiven', 'anulado_mejora', 'activo_reactivado'},
        'active':      {'withdrawing', 'cancelled', 'closed', 'forgiven', 'legal', 'anulado_devolucion', 'desistido_devolucion', 'inhumado', 'cremado'},
        'approved':    {'active', 'withdrawing', 'cancelled', 'closed', 'forgiven', 'anulado_mejora', 'activo_reactivado', 'inhumado', 'cremado'},
        'withdrawing': {'active', 'withdrawn'},
        'withdrawn':   {'desistido_devolucion'},
        'cancelled':   {'anulado_devolucion', 'anulado_mejora'},
        'anulado_devolucion':   set(),  # terminal (reembolso 70/30 o transferencia)
        'desistido_devolucion': set(),  # terminal (reembolso 70/30 o transferencia)
        'anulado_mejora':       {'activo_reactivado'},  # transiciona cuando se reactiva con precio nuevo
        'activo_reactivado':    set(),  # terminal (es el estado del NUEVO contrato reactivado)
        'legal':       {'active', 'forgiven', 'cancelled'},
        'forgiven':    set(),  # terminal
        'refuse':      set(),  # terminal
        'archived':    set(),  # terminal
        'closed':      set(),  # terminal
        'inhumado':    set(),  # terminal - fallecimiento del titular (Testarossa doPagoInhumacion tipo=INH)
        'cremado':     set(),  # terminal - fallecimiento del titular (Testarossa doPagoInhumacion tipo=CRE)
    }

    amount_financed = fields.Float(
        compute="_compute_amount_finance",
        string="Monto Financiado",
        tracking=True,
        store=True,
    )
    amount_interest_value = fields.Float(
        string="Monto de Interés", compute='_amount_all')
    amount_invoiced_residual = fields.Float(string="Factura Pendiente")
    amount_per_rate = fields.Float(string="Monto Cuota")
    amount_residual = fields.Float(string="Pendiente")
    amount_to_pay = fields.Float(string="Inicial a pagar", required=False)
    amount_total = fields.Float(string="Crédito Total",)
    category_id = fields.Many2one('sale.credit.category',
                                  string='Tipo de Tasa', required=True)
    discount_check = fields.Boolean(string="Aplicar Descuento")
    discount_amount = fields.Float(string="Monto Descuento")

    account_analytic_id = fields.Many2one(
        'account.analytic.account', string='Cuanta Análitica')

    co_debtor_id = fields.Many2one('res.partner', string='Codeudor')
    company_id = fields.Many2one('res.company', 'Company', required=True)
    credit_flow = fields.Selection([
        ('credit', 'Crédito'),
        ('quotation', 'Presupuesto'),
        ('confirmed', 'Orden Confirmada'),
        ('picking', 'Conduce'),
        ('invoice', 'Factura'),
        ('payment', 'Pagos'),], string="Flujo de Crédito")
    credit_lines = fields.One2many(
        "sale.credit.line", inverse_name="credit_id", copy=False, string="Líneas de Crédito")
    
    credit_lines_count = fields.Integer(
        string="Contar Líneas de Créditos", readonly=True, compute="_compute_sale_credit_count")
    attachment_ids = fields.One2many(
        "sale.credit.attachment", inverse_name="credit_id", copy=False, string="Adjunto")

    credit_payments = fields.One2many(
        "sale.credit.payment", "credit_id", string="Pagos de Crédito")
    credit_payments_count = fields.Integer(
        string="Credit Payments Count", readonly=True, compute='_compute_credit_payments_count')
    
    # Histórico de Refinanciamientos
    refinancing_history_ids = fields.One2many(
        'finance.refinancing.history', 'credit_id', string='Historial Refinanciamientos'
    )
    refinancing_count = fields.Integer(
        string='Monto Refinanciamientos', compute='_compute_refinancing_count'
    )

    @api.depends('refinancing_history_ids')
    def _compute_refinancing_count(self):
        for record in self:
            record.refinancing_count = len(record.refinancing_history_ids)

    def action_view_refinancing(self):
        self.ensure_one()
        return {
            'name': _('Histórico Refinanciamientos'),
            'type': 'ir.actions.act_window',
            'res_model': 'finance.refinancing.history',
            'view_mode': 'tree,form',
            'domain': [('credit_id', '=', self.id)],
            'context': {'default_credit_id': self.id},
        }

    @api.depends('credit_payments')
    def _compute_credit_payments_count(self):
        for record in self:
            record.credit_payments_count = len(record.credit_payments)

    def action_view_payments(self):
        self.ensure_one()
        return {
            'name': _('Pagos'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.payment',
            'view_mode': 'tree,form',
            'domain': [('credit_id', '=', self.id)],
            'context': {'default_credit_id': self.id},
        }

    def action_open_quick_collect(self):
        """Abre el form de recibo POS pre-llenado para cobrar este contrato.

        Reemplaza el flujo de Testarossa (link "(Caja)" desde info.php) con un
        boton directo desde el contrato. Pre-llena partner, contrato, proxima
        cuota pendiente, y la sesion POS abierta del usuario.
        """
        self.ensure_one()

        if self.state != 'approved':
            raise UserError(_(
                "Solo se puede cobrar en contratos aprobados. Estado actual: %s"
            ) % self.state)

        Session = self.env['cjg.pos.session']
        session = Session.search([
            ('state', '=', 'opened'),
            ('user_id', '=', self.env.user.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not session:
            session = Session.search([
                ('state', '=', 'opened'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
        if not session:
            raise UserError(_(
                "No hay caja abierta para %s. Abre una sesion de caja antes de cobrar."
            ) % self.company_id.display_name)

        next_line = self.credit_lines.filtered(
            lambda line: line.state in ('pending', 'paid_overdue', 'paid_reload')
        ).sorted(key=lambda line: line.expected_date_payment or fields.Date.today())[:1]
        suggested_amount = next_line.amount_residual if next_line else 0.0

        ctx = {
            'default_partner_id': self.partner_id.id,
            'default_document_type': 'credit',
            'default_sale_credit_id': self.id,
            'default_credit_contract_id': self.id,
            'default_amount_total': suggested_amount,
            'default_amount_paid': suggested_amount,
            'default_session_id': session.id,
            'default_company_id': self.company_id.id,
            'default_movement_type': 'cuota',
            'default_payment_purpose': 'other',
        }
        if next_line:
            ctx['default_credit_line_id'] = next_line.id

        return {
            'name': _('Cobrar Cuota - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'cjg.pos.payment.receipt',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def action_print_statement(self):
        return self.env.ref('cjg_finance.action_report_credit_statement').report_action(self)

    def _get_statement_lines(self):
        self.ensure_one()
        lines = []
        
        # 1. HISTORIA: Refinanciamientos (Planes Cerrados)
        # Ordenar por fecha de refinanciamiento (más viejo primero)
        for history in self.refinancing_history_ids.sorted('refinance_date'):
            # Encabezado del Plan Histórico
            plan_name = history.notes.split('-')[0] if history.notes else "Plan Anterior"
            lines.append({
                'type': 'header',
                'description': f"PLAN {plan_name} (Cerrado: {history.refinance_date.date()})",
                'is_active': False
            })
            
            # Líneas del plan histórico
            running_balance = history.old_balance + history.capital_down_payment # Aprox inicial
            # Mejor usar el saldo que ya guardamos en cada linea
            
            for line in history.line_ids: # Ya vienen ordenadas por date_maturity
                # Cuota
                lines.append({
                    'type': 'quota',
                    'number': line.number,
                    'date': line.date_maturity,
                    'description': line.description,
                    'amount': line.amount_quota,
                    'balance': line.balance + line.paid_total, # Saldo antes de pagar? No, saldo final.
                    'is_active': False
                })
                
                # Pago (si existe)
                if line.paid_total > 0:
                    lines.append({
                        'type': 'payment',
                        'number': '',
                        'date': line.payment_date,
                        'description': f"Pago: {line.payment_ref or ''}",
                        'amount': -line.paid_total, # Negativo para restar
                        'capital': line.paid_capital,
                        'interest': line.paid_interest,
                        'others': line.paid_others,
                        'balance': line.balance, # Saldo final tras pago
                        'is_active': False
                    })

            # Linea de Refinanciamiento (Cierre)
            lines.append({
                'type': 'refinance',
                'description': f"REFINANCIAMIENTO (Nuevo Saldo: {history.new_balance})",
                'amount': -history.old_balance, # Resta la deuda vieja
                'balance': 0 # Se cierra este plan
            })

        # 2. PLAN ACTUAL (Activo)
        # Calcular Balance Inicial del Plan Activo
        # En Odoo, amount_financed es el capital. amount_total es Cap + Int.
        # Asumimos que el saldo inicial es el Total a Pagar del contrato.
        active_plan_start_balance = sum(self.credit_lines.mapped('amount_fixed'))
        
        lines.append({
            'type': 'header',
            'description': f"PLAN ACTUAL (Activo) - Total: {active_plan_start_balance:,.2f}",
            'amount': active_plan_start_balance,
            'balance': active_plan_start_balance,
            'is_active': True
        })
        
        running_balance = active_plan_start_balance
        
        for line in self.credit_lines.sorted('expected_date_payment'):
            # Preparamos datos de pago
            paid_capital = 0.0
            paid_interest = 0.0
            paid_others = 0.0
            paid_total = 0.0
            payment_ref = ""
            payment_date = ""

            # Buscando pagos para consolidar en la misma linea de cuota (estilo Amortizacion)
            # Primero: sale.credit.payment.line (Nuevos pagos)
            p_lines = self.env['sale.credit.payment.line'].search([('credit_line_id', '=', line.id)])
            if p_lines:
                for pl in p_lines:
                    paid_capital += pl.amount_capital
                    paid_interest += pl.amount_interest
                    paid_others += 0 # Ajustar si hay otros
                    paid_total += pl.amount_paid
                    payment_ref += f"{pl.sale_payment_id.name or ''} "
                    payment_date = pl.sale_payment_id.payment_date or pl.sale_payment_id.date
            
            # Segundo: Fallback Legacy/Global payments (sale_credit_payment_ids M2M)
            elif line.sale_credit_payment_ids:
                 for py in line.sale_credit_payment_ids:
                    # Distribución simplificada si no hay detalle
                    paid_total += (py.amount_total / len(py.pos_payment_line_ids)) if py.pos_payment_line_ids else 0
                    payment_ref += f"{py.name} "
                    payment_date = py.payment_date or py.date

            # Actualizamos Balance
            # En tabla de amortización, el saldo baja con la CUOTA o con el PAGO?
            # En la imagen: Baja con el MONTO de la linea.
            # Si la linea representa el PAGO, baja con el pago.
            # SI es una tabla futura, baja con la Cuota.
            # Vamos a reducir el balance por el monto de la CUOTA fija, para proyectar el "Debería"
            # O si está pagado, mostramos el balance real?
            # La imagen muestra "Saldo: 17,240 -> 15,803". 17240 - 1436 = 15803.
            # Asi que decrementamos por el amount_fixed de la cuota.
            
            running_balance -= line.amount_fixed
            
            lines.append({
                'type': 'quota_row', # Combined row
                'number': f"{line.count}/{self.installment_id.name}",
                'date': line.expected_date_payment,
                'description': f"CUOTA {line.count} {line.expected_date_payment.strftime('%b %Y')}",
                'amount_quota': line.amount_fixed,
                
                # Pago info
                'receipt': payment_ref[:25] if payment_ref else '',
                'pay_date': payment_date if paid_total > 0 else '',
                'paid_capital': paid_capital if paid_total > 0 else 0.0,
                'paid_interest': paid_interest if paid_total > 0 else 0.0,
                'paid_others': paid_others if paid_total > 0 else 0.0,
                'paid_amount': -paid_total if paid_total > 0 else -line.amount_fixed, # Visual negative
                
                'balance': running_balance,
                'is_active': True 
            })
                    
        return lines
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)
    currency_id_money = fields.Many2one('res.currency', string='Moneda', required=True)
    date_approval = fields.Date(string="Fecha de Aprobación")
    date_contract = fields.Date(string="Fecha de Contrato")
    date_end = fields.Date(string="Fecha Fin")

    date_refused = fields.Date(string="Fecha de Rechazo")
    date_request = fields.Date(string="Fecha de Solicitud")
    date_start = fields.Date(string="Fecha de Inicio",
                             default=fields.Date.today(), required=True)
    frequency_id = fields.Many2one(
        'sale.credit.frequency', string="Frecuencia", required=True)
    has_message = fields.Boolean(string="Has Message")
    hide_capital_interest = fields.Boolean(string="Esconder Interés Capital")
    installment_id = fields.Many2one('sale.credit.installment',
                                     string="Cantidad Cuotas",
                                     required=False,
                                     )

    invoice_count = fields.Integer(string="Contar Facturas", readonly=True)
    invoice_ids = fields.Many2one('account.move', string="Factura")
    invoice_interest = fields.Many2one('account.move', string="Factura del Interés")
    invoice_sale = fields.Many2one('account.move', string="Factura de Venta")
    is_reconcilable = fields.Boolean(string="Conciliable")
    journal_id = fields.Many2one(
        'account.journal', string="Diario", domain="[('type', '=', 'sale')]")
    manager_id = fields.Many2one('res.users', string="Gerente")
    motorista_id = fields.Many2one('res.partner', string="Motorista", domain="[('is_motorista','=',True)]")
    
    # New fields for Collection Security
    asesor_id = fields.Many2one(
        'res.users',
        string='Asesor',
        help='Asesor de ventas que originó el contrato (del CRM)'
    )
    oficial_id = fields.Many2one(
        'res.users',
        string='Oficial de Cuenta',
        help='Oficial responsable del cobro y seguimiento del contrato',
        tracking=True,
        index=True
    )
    collection_user_id = fields.Many2one(
        'res.users',
        string='Oficial de Mantenimiento',
        help='Oficial asignado al seguimiento de mantenimiento del contrato',
        tracking=True,
        index=True
    )

    min_amount = fields.Float(string="Inicial Minimo")
    name = fields.Char(string="Referencia", required=True, readonly=True,
                       copy=False, index=True, default=lambda self: _('New'))
    origin = fields.Selection([
        ('standard', 'Standard'),
        ('sale', 'Venta'),
        ('invoice', 'Factura')],
        string="Origin", default="sale")
    overdue_count = fields.Integer(string="Contador de Moras", readonly=True)
    overdue_ids = fields.One2many("credit.overdue", "credit_id", string="Moras")
    partner_id = fields.Many2one('res.partner', string="Cliente", required=True)
    vat = fields.Char(related='partner_id.vat', string="Identificación", store=True)
    partner_signature = fields.Binary(string="Firma Cliente")
    payment_count = fields.Integer(string="Contador de Pagos", readonly=True)
    payment_backdated = fields.Integer(
        string="payment_count", compute='backdated_counter')
    payment_status = fields.Selection([
        ('not_paid', 'No Pagadas'),
        ('cancel', 'Proceso cancelado'),
        ('in_payment', 'En proceso de pago'),
        ('paid_backdated', 'Pago atrasado'),
        ('paid_backdateds', 'Pagos atrasados'),
        ('paid', 'Pagado')], default='not_paid', string='Estatus de pago')
    # payment_ids = fields.Many2many("account.payment", string="Abono a Cuota(s)")
    # account_payment_ids = fields.One2many(
    #     'account.payment', 'sale_credit_id', string="Pagos")
    payment_msg = fields.Char(string="Mensaje de Pagos")
    payments = fields.Integer(string="Contador de Pagos")
    percent_financing = fields.Float(string="Financiado(%)", default=0.0)
    percent_interest = fields.Float(string="TAE(%)", default=0.0)
    picking_id = fields.Many2one('stock.picking', string="Conduce")
    product_id = fields.Many2one(
        'product.product', string="Propiedad", 
        domain="[('sale_ok', '=', True),]", 
        required=False,
        check_company=False
    )
    re_scheduled = fields.Boolean(string="Reprogramar")
    ref_partner_id = fields.Many2one('res.partner', string="Referencia Personal")
    sale_id = fields.Many2one('sale.order', string="Venta",
                              domain="[('partner_id', '=', partner_id),]")
    show_reschedule_button = fields.Boolean(string="Mostrar Botón Reprogramar")
    method = fields.Selection([
        ('flat', 'Interes Simple (Lineal)'),
        ('reducing', 'Interes Compuesto (Francés)')
    ], string="Método de Interés", default='flat')

    # CRM integration flags (present even without CRM module to avoid domain errors)
    is_from_crm = fields.Boolean(string='Creado desde CRM', default=False)
    crm_state = fields.Selection([
        ('draft', 'Borrador'),
        ('quoted', 'Cotizado'),
        ('client_approved', 'Aprobado por Cliente'),
        ('client_rejected', 'Rechazado por Cliente')
    ], string="Estado CRM", default='draft')

    contract_product_type = fields.Selection([
        ('basic', 'Básico')
    ], string='Tipo de Contrato', default='basic', required=True)
    
    # Campo para migración Testarossa
    tipo_contrato_legacy = fields.Selection([
        ('0', 'Tipo 0 - Rebajado'),
        ('1', 'Tipo 1 - Balance Cliente')
    ], string="Tipo Contrato Testarossa", readonly=True, 
       help="Tipo de contrato en el sistema legado Testarossa para referencia de migración")

    apply_manual_currency_exchange = fields.Boolean(string='Ver tasa de divisa')
    manual_currency_exchange_rate = fields.Float(string='Cambio de divisa')
    active_manual_currency_rate = fields.Boolean(
        'active Manual Currency', default=False)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('requested', 'Solicitado'),
        ('pending', 'Por Verificar'),  # Estado 13 Testarossa
        ('verified', 'Verificacion Documento'),
        ('resent', 'Traspasado'),
        ('approved', 'Aprobado'),
        ('active', 'Activo'),  # Estado 1 Testarossa - Alias para 'approved'
        ('withdrawing', 'Por Desistir'),  # Estado 23 Testarossa
        ('withdrawn', 'Desistido'),  # Estado 25 Testarossa
        ('legal', 'En Legal'),  # Estado 47 Testarossa
        ('forgiven', 'Deuda Condonada'),  # Estado 61 Testarossa
        ('refuse', 'Rechazado'),
        ('archived', 'Archivado'),
        ('cancelled', 'Cancelado/Anulado'),  # Estados 26,55,56,57,64 Testarossa
        ('closed', 'Completado/Saldado'),  # Estado 20 Testarossa
        ('anulado_devolucion', 'Anulado Devolución'),
        ('desistido_devolucion', 'Desistido Devolución'),
        ('anulado_mejora', 'Anulado Mejora'),  # legacy id_status
        ('activo_reactivado', 'Activo (Reactivado)'),  # legacy estatus 39
        ('inhumado', 'Inhumado'),  # terminal - fallecimiento del titular (Testarossa doPagoInhumacion tipo=INH)
        ('cremado', 'Cremado'),  # terminal - fallecimiento del titular (Testarossa doPagoInhumacion tipo=CRE)
    ], string="Estado", required=True, readonly=True, copy=False, tracking=True, default='draft')
    
    closed_date = fields.Date(
        string="Fecha de Cierre",
        help=(
            "Fecha en que el contrato pasa a estado terminal (closed, forgiven, "
            "inhumado, cremado, etc.). Se setea automáticamente desde "
            "action_to_closed() y desde optimization_dinamic() (cierre automático "
            "al pagar la última cuota). También lo setea el wizard de condonación "
            "de deuda (debt.forgiveness.wizard) al pasar el contrato a 'forgiven'."
        ),
    )
    migration_status_label = fields.Char(string="Estatus de Migración", compute='_compute_migration_status_label')

    @api.depends('state', 'closed_date')
    def _compute_migration_status_label(self):
        for record in self:
            label = ""
            if record.state == 'closed' and record.closed_date:
                date_str = record.closed_date.strftime('%d/%m/%Y')
                label = f"SALDADO EL {date_str}"
            record.migration_status_label = label

    has_overdue = fields.Boolean(string="Tiene atraso", compute='_compute_has_overdue', store=True)
    credit_Adeudado = fields.Monetary(
        compute='_credit_Adeudado', string="Total Adeudado", store=True)
    credit_amount = fields.Monetary(compute='_credit_pay', string="Total Pagado", store=True)
    computed_currency_rate = fields.Float(compute='_compute_currency_rate', store=True)
    archived_product_ids = fields.Many2many(
        'sale.credit.line', string='Archived Products', compute='_compute_archived')
    archived_product_count = fields.Integer(
        "Archived Product", compute='_compute_archived')
    refinance_active = fields.Boolean(
        default=False, help="Set active to false to hide the Account Tag without removing it.")
    active = fields.Boolean(
        default=True, help="Set active to false to hide the Account Tag without removing it.")
    error_log = fields.Text(string="Error Log")
    internal_notes = fields.Text(string="notas")
    term_conditions = fields.Text(string="Terminos y Condiciones")
    to_invoice = fields.Boolean(string="A Facturar")
    total_sold = fields.Float(string="Total Vendido")
    total_charges_abonos = fields.Float(string="Total Cargos/Abonos", help="Suma de cargos y abonos (moras y otros) migrados de Testarossa")
    type_id = fields.Selection([
        ('finan', 'Financiamiento'),
        ('presper', 'Prestamo Personal')],
        string="Tipo", required=True, readonly=True, copy=False, tracking=True, default='finan')
    update_payment = fields.Boolean(string="Actualizar Pago")
    user_id = fields.Many2one('res.users', string="Usuario",
                              default=lambda self: self.env.user)
    warehouse_id = fields.Many2one('stock.warehouse', string="Almacén")
    customize = fields.Boolean(string='Personalizar cuotas', default=False)
    customize_date = fields.Boolean(string='Personalizar Fin de pago', default=False)
    use_percentages = fields.Boolean(string='Configurar por Porcentajes', default=False)
    sale_valid = fields.Boolean(string='Validar Venta', default=False)
    config_mora = fields.Many2one(
        'credit.overdue.configuration', string="Configuracion de mora")
    apply_mora = fields.Boolean(string='Aplicar mora', default=False)
    config_general = fields.Boolean(string='general de mora', default=False)
    loan_amount = fields.Float(string="Monto de prestamo")
    existing_payments = fields.One2many('sale.credit.existing.payment', 'credit_id', string="Pagos Existentes Temporales")
    
    # Cargos y Abonos (Moras y Ajustes)
    charge_ids = fields.One2many(
        'sale.credit.charge',
        'credit_id',
        string='Cargos/Abonos',
        help='Cargos (moras, penalidades) y Abonos (descuentos, condonaciones) aplicados al contrato'
    )
    
    charge_count = fields.Integer(
        string='# Cargos/Abonos',
        compute='_compute_charge_count'
    )
    
    total_charges = fields.Monetary(
        string='Total Cargos',
        compute='_compute_charges',
        store=True,
        currency_field='currency_id',
        help='Suma de todos los cargos aplicados (moras, penalidades, etc.)'
    )
    
    total_credits = fields.Monetary(
        string='Total Abonos',
        compute='_compute_charges',
        store=True,
        currency_field='currency_id',
        help='Suma de todos los abonos aplicados (descuentos, condonaciones, etc.)'
    )
    
    balance_adjustments = fields.Monetary(
        string='Ajustes Netos',
        compute='_compute_charges',
        store=True,
        currency_field='currency_id',
        help='Diferencia entre cargos y abonos (Cargos - Abonos)'
    )
    
    # ========== CAMPOS PARA FLUJO DESDE PLANILLA (CRM) ==========
    
    # Relación con planilla origen
    crm_lead_id = fields.Many2one(
        'crm.lead',
        string='Planilla Origen',
        readonly=True,
        copy=False,
        tracking=True,
        help='Planilla desde la cual se creó este contrato'
    )
    
    # Indicador de contrato al contado (100% pagado desde inicio)
    is_cash_contract = fields.Boolean(
        string='Contrato Al Contado',
        default=False,
        help='True si el contrato fue pagado al 100% antes de crearse (sin cuotas)'
    )
    
    # Monto del pago inicial
    initial_payment_total = fields.Monetary(
        string='Pago Inicial Recibido',
        currency_field='currency_id',
        help='Suma de todos los pagos iniciales recibidos antes de crear el contrato'
    )
    
    # Método de Pago/Cobro (match con CRM transfer_method y Testarossa forpago)
    payment_method = fields.Selection([
        ('card', 'Tarjeta Crédito'),
        ('debit', 'Débito Automático'),
        ('courier', 'Mensajería'),
        ('motorista', 'Motorista'),
        ('transfer', 'Transferencia'),
        ('deposit', 'Depósito'),
        ('office', 'Oficina/Taquilla'),
        ('online', 'Pago en Línea'),
        ('other', 'Otros'),
    ], string='Método de Pago', tracking=True,
       help='Método mediante el cual el cliente realizará los pagos del contrato')

    contract_process_type = fields.Selection(
        [
            ('new', 'Venta Nueva'),
            ('improvement', 'Mejora'),
            ('reactivation', 'Reactivación'),
        ],
        string='Proceso Comercial',
        default='new',
        tracking=True,
        help='Proceso comercial que originó este contrato.'
    )
    origin_credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato Origen',
        copy=False,
        tracking=True,
        help='Contrato anterior desde el cual nace esta mejora o reactivación.'
    )
    derived_credit_ids = fields.One2many(
        'sale.credit',
        'origin_credit_id',
        string='Contratos Derivados'
    )
    derived_credit_count = fields.Integer(
        string='Contratos Derivados',
        compute='_compute_derived_credit_count',
    )
    capitalized_amount = fields.Monetary(
        string='Monto Capitalizado',
        currency_field='currency_id',
        default=0.0,
        tracking=True,
        help='Monto trasladado desde el contrato anterior en un proceso de mejora.'
    )
    reactivation_penalty_rate = fields.Float(
        string='% Penalidad Reactivación',
        default=0.0,
        tracking=True,
        help='30% en la primera reactivación y 50% si el contrato ya había sido reactivado.'
    )
    reactivation_penalty_amount = fields.Monetary(
        string='Penalidad Reactivación',
        currency_field='currency_id',
        default=0.0,
        tracking=True,
        help='Penalidad aplicada cuando el contrato nace por reactivación.'
    )
    reactivation_penalty_distributed = fields.Boolean(
        string='Penalidad de Reactivación Distribuida',
        default=False,
        copy=False,
        readonly=True,
        help='Control técnico para impedir que la penalidad se agregue más de una vez.',
    )
    process_detail_status = fields.Selection(
        [
            ('normal', 'Normal'),
            ('anulado_mejora', 'Anulado Mejora'),
            ('anulado_devolucion', 'Anulado Devolución'),
            ('desistido_devolucion', 'Desistido Devolución'),
            ('reactivado', 'Reactivado'),
        ],
        string='Detalle de Proceso',
        default='normal',
        tracking=True,
        help='Detalle de negocio que complementa el estado técnico del contrato.'
    )
    process_capital_paid = fields.Monetary(
        string='Capital Pagado (Proceso)',
        currency_field='currency_id',
        compute='_compute_process_origin_metrics',
    )
    process_interest_paid = fields.Monetary(
        string='Interés Pagado (Proceso)',
        currency_field='currency_id',
        compute='_compute_process_origin_metrics',
    )
    process_pending_installments = fields.Integer(
        string='Cuotas Pendientes (Proceso)',
        compute='_compute_process_origin_metrics',
    )
    process_state_label = fields.Char(
        string='Estado de Proceso',
        compute='_compute_process_origin_metrics',
    )
    process_default_penalty_rate = fields.Float(
        string='Penalidad Sugerida',
        compute='_compute_process_origin_metrics',
    )
    process_product_type = fields.Selection(
        [('property', 'Propiedad'), ('service', 'Servicio Funerario')],
        string='Tipo de Producto Proceso',
        compute='_compute_process_origin_metrics',
    )
    process_reference_amount = fields.Monetary(
        string='Monto Referencia Proceso',
        currency_field='currency_id',
        compute='_compute_process_origin_metrics',
    )
    process_improvement_eligible = fields.Boolean(
        string='Elegible para Mejora',
        compute='_compute_process_origin_metrics',
    )

    # ========== CAMPOS DEVOLUCIÓN (OPCIÓN 3) ==========

    devolucion_method = fields.Selection([
        ('cheque', 'Cheque'),
        ('transfer', 'Transferencia Bancaria'),
    ], string='Método de Devolución')

    devolucion_reference = fields.Char(string='Referencia Devolución')
    devolucion_date = fields.Date(string='Fecha Emisión Devolución')
    devolucion_amount = fields.Monetary(string='Monto Devuelto', currency_field='currency_id')
    devolucion_notes = fields.Text(string='Notas Devolución')

    # ========== CAMPOS NO REEMBOLSO (OPCIÓN 2) ==========

    no_refund_registered = fields.Boolean(string='Sin Reembolso Registrado', default=False)
    no_refund_date = fields.Date(string='Fecha Registro Sin Reembolso')
    no_refund_user_id = fields.Many2one('res.users', string='Registrado Por')

    # Fecha de cierre/saldado (para contratos completados)
    closed_date = fields.Date(
        string='Fecha de Cierre',
        readonly=True,
        help='Fecha en que el contrato fue completamente saldado'
    )
    
    # Relación con recibos de pago inicial
    payment_receipt_ids = fields.One2many(
        'cjg.pos.payment.receipt',
        'sale_credit_id',
        string='Recibos de Pago',
        help='Recibos de pago inicial vinculados a este contrato'
    )
    
    payment_receipt_count = fields.Integer(
        compute='_compute_payment_receipt_count',
        string='Cantidad de Recibos'
    )
    
    # Mantenimiento
    maintenance_contract_ids = fields.One2many(
        'maintenance.contract',
        'sale_credit_id',
        string='Contratos de Mantenimiento'
    )
    maintenance_contract_count = fields.Integer(
        compute='_compute_maintenance_contract_count',
        string='# Contratos Mto.'
    )
    
    @api.depends('maintenance_contract_ids')
    def _compute_maintenance_contract_count(self):
        for record in self:
            record.maintenance_contract_count = len(record.maintenance_contract_ids)

    @api.constrains(
        'contract_process_type',
        'origin_credit_id',
        'partner_id',
        'capitalized_amount',
        'reactivation_penalty_amount',
    )
    def _check_contract_process_data(self):
        for record in self:
            if record.capitalized_amount and record.capitalized_amount < 0:
                raise ValidationError(_('El monto capitalizado no puede ser negativo.'))
            if record.reactivation_penalty_amount and record.reactivation_penalty_amount < 0:
                raise ValidationError(_('La penalidad de reactivación no puede ser negativa.'))
            if record.contract_process_type in ('improvement', 'reactivation') and not record.origin_credit_id:
                raise ValidationError(_('Debe indicar un contrato origen para mejoras o reactivaciones.'))
            if record.contract_process_type != 'reactivation' and record.reactivation_penalty_amount:
                raise ValidationError(_('Solo las reactivaciones pueden llevar penalidad.'))
            if record.origin_credit_id and record.partner_id and record.origin_credit_id.partner_id != record.partner_id:
                raise ValidationError(_('El contrato origen debe pertenecer al mismo cliente.'))
            if (
                record.origin_credit_id
                and record.company_id
                and record.origin_credit_id.company_id != record.company_id
            ):
                raise ValidationError(_(
                    'El contrato origen y el contrato derivado deben pertenecer '
                    'a la misma empresa.'
                ))
            if record.contract_process_type == 'reactivation' and record.origin_credit_id:
                if record.origin_credit_id.state not in ('cancelled', 'withdrawn'):
                    raise ValidationError(_(
                        'Solo se pueden reactivar contratos en estado Anulado o Desistido.'
                    ))
                currency = (
                    record.currency_id_money
                    or record.currency_id
                    or record.company_id.currency_id
                )
                expected_penalty = currency.round(
                    (record.origin_credit_id.process_capital_paid or 0.0)
                    * ((record.reactivation_penalty_rate or 0.0) / 100.0)
                )
                if not currency.is_zero(
                    (record.reactivation_penalty_amount or 0.0)
                    - expected_penalty
                ):
                    raise ValidationError(_(
                        'La penalidad de reactivación debe calcularse sobre el '
                        'capital pagado del contrato origen. Esperado: %(expected)s.'
                    ) % {'expected': expected_penalty})
            
    def action_view_maintenance_contracts(self):
        """Smart button para ver contratos de mantenimiento."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Contratos de Mantenimiento',
            'res_model': 'maintenance.contract',
            'view_mode': 'tree,form',
            'domain': [('sale_credit_id', '=', self.id)],
            'context': {
                'default_sale_credit_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_company_id': self.company_id.id,
            }
        }

    def action_create_maintenance_contract(self):
        """Crear un contrato de mantenimiento vinculado a este contrato."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear Mantenimiento',
            'res_model': 'maintenance.contract',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_sale_credit_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_company_id': self.company_id.id,
            }
        }
    
    # ========== MÉTODOS PARA CARGOS Y ABONOS ==========
    
    @api.depends('charge_ids')
    def _compute_charge_count(self):
        """Cuenta cuántos cargos/abonos tiene el contrato"""
        for record in self:
            record.charge_count = len(record.charge_ids)
    
    @api.depends('charge_ids', 'charge_ids.amount', 'charge_ids.state', 'charge_ids.charge_type')
    def _compute_charges(self):
        """Calcula totales de cargos y abonos aplicados"""
        for record in self:
            posted_charges = record.charge_ids.filtered(lambda c: c.state == 'posted')
            charges = sum(posted_charges.filtered(lambda c: c.charge_type == 'charge').mapped('amount'))
            credits = sum(posted_charges.filtered(lambda c: c.charge_type == 'credit').mapped('amount'))
            
            record.total_charges = charges
            record.total_credits = credits
            record.balance_adjustments = charges - credits
    
    def action_view_charges(self):
        """Smart button para ver cargos y abonos"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cargos y Abonos',
            'res_model': 'sale.credit.charge',
            'view_mode': 'tree,form',
            'domain': [('credit_id', '=', self.id)],
            'context': {
                'default_credit_id': self.id,
                'default_partner_id': self.partner_id.id
            }
        }

    # ========== FIX: calcularAbonoACapital (legacy class.Contratos.php) ==========
    def action_apply_payment_with_capital_abono(self, payment, sobrante):
        """Replica class.Contratos.php::calcularAbonoACapital.

        Cuando un cliente paga mas que la cuota, el legacy hace:
          1. Paga la cuota completa.
          2. Si sobra, paga la penalidad pendiente (si hay).
          3. La diferencia se abona a CAPITAL, reduciendo el monto total
             adeudado (distribuido entre las cuotas restantes, no reduce
             el numero de cuotas).

        H-C20: el flujo previo de ``_apply_payment_to_credit_lines`` solo
        loggeaba el sobrante. Este metodo lo reaplica de forma
        estructurada para que el dinero "no se pierda" en silencio.

        :param payment: sale.credit.payment que origino el sobrante
        :param sobrante: monto no asignado tras distribuir la cuota
        :return: dict con detalle de la distribucion (penalidad / capital)
        """
        self.ensure_one()
        if sobrante <= 0.01:
            return {'penalty': 0.0, 'capital_abono': 0.0, 'lines_affected': 0}

        sobrante_remaining = float(sobrante)
        result = {
            'penalty': 0.0,
            'capital_abono': 0.0,
            'lines_affected': 0,
        }

        # 1. Pago de penalidad pendiente.
        # NOTA: ``amount_others`` en sale.credit.line agrupa penalidad +
        # mantenimiento sin distinguir; se usa como proxy de la penalidad
        # legacy. El contrato expone ``reactivation_penalty_amount`` y la
        # suma de cargos tipo ``charge`` posted como senales mas limpias,
        # pero el legacy los trata como un solo monto por linea.
        pending_penalty = sum(
            (line.amount_others or 0.0)
            for line in self.credit_lines
            if line.state not in ('paid', 'cancelled')
        )
        penalty_payment = min(sobrante_remaining, max(0.0, pending_penalty))
        if penalty_payment > 0.01:
            charge = self.env['sale.credit.charge'].create({
                'credit_id': self.id,
                'charge_type': 'charge',
                'amount': penalty_payment,
                'reason': _('Pago de penalizacion (abono) desde recibo %s')
                         % (payment.name or ''),
                'date': fields.Date.today(),
            })
            charge.action_post()
            result['penalty'] = penalty_payment
            sobrante_remaining -= penalty_payment

        # 2. Abono a capital: distribuir entre cuotas pendientes (reduce monto).
        if sobrante_remaining > 0.01:
            unpaid_lines = self.credit_lines.filtered(
                lambda l: l.state not in ('paid', 'cancelled')
            ).sorted(key=lambda l: l.expected_date_payment or fields.Date.today())
            if unpaid_lines:
                per_line = sobrante_remaining / len(unpaid_lines)
                for line in unpaid_lines:
                    line.write({
                        'amount_capital': max(
                            0.0,
                            (line.amount_capital or 0.0) - per_line,
                        ),
                        'amount_residual': max(
                            0.0,
                            (line.amount_residual or 0.0) - per_line,
                        ),
                    })
                result['capital_abono'] = sobrante_remaining
                result['lines_affected'] = len(unpaid_lines)

                charge = self.env['sale.credit.charge'].create({
                    'credit_id': self.id,
                    'charge_type': 'credit',
                    'amount': sobrante_remaining,
                    'reason': _('Abono a capital (sobrante de pago) desde '
                                'recibo %s') % (payment.name or ''),
                    'date': fields.Date.today(),
                })
                charge.action_post()
                self.message_post(body=_(
                    "calcularAbonoACapital: sobrante de %s reaplicado. "
                    "Penalidad: %s. Abono a capital: %s distribuido en "
                    "%s cuotas (%s por cuota)."
                ) % (
                    float(sobrante),
                    result['penalty'],
                    result['capital_abono'],
                    result['lines_affected'],
                    per_line,
                ))
        return result

    # def recover_existing_payments(self):
    #     AccountPayment = self.env['account.payment']
    #     SaleCreditPayment = self.env['sale.credit.payment']
        
    #     credits_updated = set()

    #     for credit in self:
    #         # Buscar todos los pagos asociados a este crédito
    #         credit_payments = AccountPayment.search([
    #             ('sale_credit_id', '=', credit.id),
    #             ('state', '=', 'posted')
    #         ], order='date')

    #         # Ordenar las líneas de crédito por fecha de pago esperada
    #         credit_lines = credit.credit_lines.sorted(key=lambda l: l.expected_date_payment)

    #         for payment in credit_payments:
    #             sale_credit_payment = SaleCreditPayment.search([('payment_id', '=', payment.id)], limit=1)
                
    #             # Usar amount_total de sale.credit.payment si existe, de lo contrario usar payment.amount
    #             amount_to_allocate = sale_credit_payment.amount_total if sale_credit_payment else payment.amount
                
    #             for line in credit_lines:
    #                 if line.amount_residual > 0 and amount_to_allocate > 0:
    #                     allocated_amount = min(line.amount_residual, amount_to_allocate)
                        
    #                     # Actualizar la línea de crédito
    #                     line.write({
    #                         'amount_paid_total': line.amount_paid_total + allocated_amount,
    #                         'amount_residual': line.amount_residual - allocated_amount,
    #                     })

    #                     # Actualizar sale_credit_payment_ids de manera segura
    #                     if sale_credit_payment:
    #                         existing_ids = line.sale_credit_payment_ids.ids
    #                         if sale_credit_payment.id not in existing_ids:
    #                             line.sale_credit_payment_ids = [(4, sale_credit_payment.id)]
    #                     else:
    #                         # line.payment_pay_ids = [(4, payment.id)]
    #                         pass

    #                     amount_to_allocate -= allocated_amount

    #                     # Actualizar el estado de la línea si es necesario
    #                     if line.amount_residual <= 0:
    #                         line.state = 'paid'

    #             if amount_to_allocate > 0:
    #                 credit.message_post(body=_(f"El pago {payment.name} tiene un excedente de {amount_to_allocate} que no se pudo asignar a ninguna línea de crédito."))

    #             credits_updated.add(credit.id)

    #         credit.optimization_dinamic()
    #         credit.message_post(body=_("Se han recuperado y reconectado los pagos existentes."))

    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'display_notification',
    #         'params': {
    #             'title': _('Recuperación de pagos completada'),
    #             'message': _('Se han procesado %s créditos y recuperado sus pagos existentes.') % len(credits_updated),
    #             'type': 'success',
    #             'sticky': False,
    #         }
    #     }

    @api.depends('credit_lines.state')
    def _compute_has_overdue(self):
        for credit in self:
            states = set(credit.credit_lines.mapped('state'))
            credit.has_overdue = bool({'paid_overdue', 'paid_reload'} & states)
    
    # ========== MÉTODOS PARA FLUJO DESDE PLANILLA ==========
    # NOTE: payment_receipt methods moved to cjg_finance_pos module
    
    def action_view_planilla(self):
        """Smart button para ver la planilla origen"""
        self.ensure_one()
        if not self.crm_lead_id:
            raise UserError("Este contrato no tiene una planilla origen asociada.")
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Planilla Origen',
            'res_model': 'crm.lead',
            'res_id': self.crm_lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
    
    @api.depends('payment_receipt_ids')
    def _compute_payment_receipt_count(self):
        """Cuenta cuántos recibos de pago tiene el contrato"""
        for contract in self:
            contract.payment_receipt_count = len(contract.payment_receipt_ids)
    
    def action_view_payment_receipts(self):
        """Smart button para ver recibos de pago inicial"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Recibos de Pago Inicial',
            'res_model': 'cjg.pos.payment.receipt',
            'view_mode': 'tree,form',
            'domain': [('sale_credit_id', '=', self.id)],
            'context': {'default_sale_credit_id': self.id}
        }
    

    @api.model
    def action_generate_report(self):
        credits = self.env['sale.credit'].search([('state', '=', 'approved')])
        for record in credits:
            lines_to_update = record.credit_lines.filtered(lambda l: not l.date_payment and l.expected_date_payment < fields.Date.today())
            lines_to_update.write({'state': 'paid_overdue'})
            lines_to_reload = record.credit_lines.filtered(lambda l: l.overdue_residual != 0)
            lines_to_reload.write({'state': 'paid_reload'})

            record.payment_status_credit()
            record.followup_status()
        return True

    def payment_status_credit(self):
        line_count = self.env['sale.credit.line'].search_count([
            ('credit_id', '=', self.id),
            ('state', '=', 'paid_overdue')
        ])
        if line_count == 1:
            self.payment_status = 'paid_backdated'
        elif line_count > 1:
            self.payment_status = 'paid_backdateds'

    def followup_status(self):
        line = self.env['sale.credit.line'].search([('credit_id', '=', self.id)])

        seguimiento = self.env['sale_credit.followup']
        exist = seguimiento.search([('name', '=', self.name)])

        followup_status = 'no_action_needed'

        today = fields.Date.context_today(self)

        if any(l.state in ['paid_reload', 'paid_overdue'] for l in line):
            followup_status = 'in_need_of_action'

        if not exist:
            record = self.env['sale_credit.followup'].create({
                'name': f'{self.name}',
                'respatner': self.partner_id.id,
                'followup_status_sale_credit': followup_status,
                'sale_credit_reminder_type': 'automatico',
                'followup_line_id_sale_credit': 1,
                'followup_responsible_id_sale_credit': self.user_id.id
            })
        else:
            exist.write({
                'followup_status_sale_credit': followup_status,
                'followup_responsible_id_sale_credit': self.user_id.id
            })

        days_to_remind = exist.followup_line_id_sale_credit.delay

        for l in line.filtered(lambda x: x.state == 'paid_overdue'):
            followup_line = self.env['followup.sale.credit'].search(
                [('credit_id', '=', l.credit_id.id), ('count', '=', l.count)], limit=1)
            if followup_line and followup_line.can_be_dist:
                continue

            if l.date_payment:
                overdue_days = (today - l.date_payment).days
            else:
                overdue_days = (today - l.expected_date_payment).days

            if overdue_days >= days_to_remind:
                message = f"El cliente {self.partner_id.name} tiene {overdue_days} días atrasados en su pago de la línea {l.count}."
                try:
                    self.error_log = f"{self.error_log}\n{message}"
                    for record in self:
                        record.message_post(body=message)
                except Exception as e:
                    raise UserError(f"Error al enviar el mensaje: {e}")

        for pending_line in line.filtered(lambda x: x.state == 'pending'):
            followup_line = self.env['followup.sale.credit'].search(
                [('credit_id', '=', pending_line.credit_id.id), ('count', '=', pending_line.count)], limit=1)
            if followup_line and followup_line.can_be_dist:
                continue

            days_left = (pending_line.expected_date_payment - today).days

            if days_left == days_to_remind:
                if pending_line.state == 'paid':
                    message = f"La línea de crédito {pending_line.count} para el cliente {self.partner_id.name} ya ha sido pagada."
                else:
                    message = f"El cliente {self.partner_id.name} le faltan {days_left} días para su próximo pago del crédito {self.name} por el monto de {pending_line.amount_residual} en la línea {pending_line.count}."

                try:
                    self.error_log = f"{self.error_log}\n{message}"
                    for record in self:
                        record.message_post(body=message)
                except Exception as e:
                    raise UserError(f"Error al enviar el mensaje: {e}")

                if pending_line.state != 'paid':
                    email_to = self.partner_id.email
                    if email_to:
                        mail_values = {
                            'subject': f'Recordatorio de pago',
                            'body_html': f'<div><p>Estimado/a {self.partner_id.name},</p>'
                            f'<p>Le recordamos que su próximo pago del crédito {self.name} es en {days_left} días por el monto de {pending_line.amount_residual}.</p>'
                            f'<p>Gracias,</p>'
                            f'<p>INNOVASOL</p></div>',
                            'email_to': email_to,
                        }
                        self.env['mail.mail'].create(mail_values).send()
                    else:
                        self.error_log = f"{self.error_log}\nNo se pudo enviar el correo electrónico al cliente {self.partner_id.name} debido a que no se ha definido una dirección de correo electrónico."
    
    @api.model
    def send_payment_reminders(self):
        """
        Enviar recordatorios de pagos próximos (próximos 7 días)
        Método llamado por cron job
        """
        today = fields.Date.context_today(self)
        next_week = today + relativedelta(days=7)
        
        # Buscar créditos activos con cuotas próximas a vencer
        credits = self.search([
            ('state', '=', 'approved'),
            ('credit_lines.expected_date_payment', '>=', today),
            ('credit_lines.expected_date_payment', '<=', next_week),
            ('credit_lines.state', '=', 'pending')
        ])
        
        for credit in credits:
            # Obtener cuotas próximas a vencer
            upcoming_lines = credit.credit_lines.filtered(
                lambda l: l.state == 'pending' and 
                today <= l.expected_date_payment <= next_week
            )
            
            if upcoming_lines and credit.partner_id.email:
                # Enviar correo de recordatorio
                template = self.env.ref('cjg_finance.email_template_payment_reminder', raise_if_not_found=False)
                if template:
                    template.send_mail(credit.id, force_send=True)
        
        return True



    @api.depends('credit_lines.amount_interest')
    def _amount_all(self):
        for each in self:
            each.amount_interest_value = sum(each.credit_lines.mapped('amount_interest'))

    def valid_balance_user(self):
        user_balance = self.env['sale_credit.preaprovado'].search(
            [('client', '=', self.partner_id.id)], limit=1)
        if not user_balance:
            return

        total_sold = sum(self.env['sale.credit'].search(
            [('partner_id', '=', self.partner_id.id), ('state', 'not in', ['refuse', 'cancelled'])]
        ).mapped('total_sold'))

        balance = user_balance.credit_preapproved - total_sold

        if balance < self.total_sold:
            raise ValidationError(
                _("El contacto {} no dispone de saldo suficiente para financiar").format(self.partner_id.name)
            )


    @api.onchange('product_id', 'category_id', 'percent_financing', 'origin', 'loan_amount')
    def _change_price(self):
        """
        Change the price based on the product or the custom amount entered.
        """
        for record in self:
            if record.origin == 'standard':
                record.total_sold = record.loan_amount
                self._fields['total_sold'].string = "Total Vendido"


            else:
                if record.product_id:
                    record.total_sold = record.product_id.list_price
                    # pass

            if record.percent_financing == 0 and record.category_id:
                record.percent_financing = record.category_id.percent_financing
            
            if record.percent_interest == 0 and record.category_id:
                record.percent_interest = record.category_id.percent_interest


            min_pay = record.total_sold * (record.percent_financing / 100)
            record.min_amount = record.total_sold - min_pay

            if record.partner_id and record.category_id.use_credit:
                record.valid_balance_user()

    @api.depends('credit_lines')
    def _compute_sale_credit_count(self):
        for sc in self:
            creditlines = sc.credit_lines
            sc.credit_lines_count = len(creditlines)

    @api.constrains('amount_to_pay')
    def _constrains_amount_to_pay(self):
        for record in self:
            if record.amount_to_pay < record.min_amount:
                raise ValidationError(
                    _('El "Inicial a Pagar" no puede ser menor que el "Inicial Minimo"'))
            elif record.amount_to_pay > record.total_sold:
                raise ValidationError(
                    _('El "Inicial a Pagar" no puede ser mayor que el "Total Vendido"'))
        
    @api.constrains('loan_amount')
    def _constrains_loan_amount(self):
        for record in self:
            if record.loan_amount <= 0 and record.origin == 'standard':
                raise ValidationError(
                    _('El monto del prestamo debe ser mayor a 0'))

    @api.constrains('state', 'origin_credit_id', 'contract_process_type')
    def _check_unique_pending_process(self):
        """Valida que no exista más de un proceso pendiente (reactivación, mejora, etc.)
        por contrato origen. Equivalente a la validación legacy de testarossa
        class.Contratos.php:6703-6715 (estatus=34/35).
        """
        terminal_states = ('closed', 'cancelled', 'withdrawn', 'refuse', 'forgiven', 'archived')
        process_types = ('reactivation', 'improvement')
        for record in self:
            if not record.contract_process_type:
                continue
            if record.contract_process_type not in process_types:
                continue
            if record.state in terminal_states:
                continue
            origin = record.origin_credit_id or record
            domain = [
                ('id', '!=', record.id),
                ('contract_process_type', '=', record.contract_process_type),
                ('state', 'not in', terminal_states),
            ]
            if record.origin_credit_id:
                domain.append(('origin_credit_id', '=', origin.id))
            else:
                domain.append(('id', '=', record.id))
            existing = self.search(domain, limit=1)
            if existing:
                raise ValidationError(_(
                    "Ya existe un proceso de tipo '%s' pendiente para este contrato (%s). "
                    "Cancele o cierre el proceso existente antes de crear uno nuevo."
                ) % (
                    dict(record._fields['contract_process_type'].selection).get(
                        record.contract_process_type, record.contract_process_type
                    ),
                    existing.name,
                ))

    @api.depends('percent_interest', 'total_sold', 'amount_to_pay', 'discount_amount', 'reactivation_penalty_amount')
    def _compute_amount_finance(self):
        for rec in self:
            if rec.total_sold:
                net_sale = (rec.total_sold or 0.0) - (rec.discount_amount or 0.0)
                rec.amount_financed = max(net_sale - (rec.amount_to_pay or 0.0) + (rec.reactivation_penalty_amount or 0.0), 0.0)
            else:
                rec.amount_financed = 0

    @api.constrains('manual_currency_exchange_rate')
    def manual_currency_validate(self):
        for record in self:
            if record.manual_currency_exchange_rate < 0:
                raise ValidationError(_('EL CAMBIO DE DIVISA DEBE SER MAYOR QUE 0'))
    campo_calculado = fields.Char(
        string='Campo Calculado', compute='_compute_campo_calculado', inverse='_set_campo_calculado', store=True)

    @api.depends('amount_to_pay')
    def _compute_campo_calculado(self):
        if self.env.context.get('test_skip_compute_loan'):
            for record in self:
                record.campo_calculado = ''
            return
        for record in self:
            try:
                resultado = record.with_context(skip_unlink_lines=True).compute_loan()
            except Exception:
                resultado = ''
            record.campo_calculado = resultado

    def _set_campo_calculado(self):
        pass

    def compute_loan(self):
        SaleCreditLines = self.env['sale.credit.line']
        # H-C01: Proteger unlink dentro de savepoint y NUNCA borrar
        # líneas con pagos aplicados (H-C18). El contexto
        # `skip_unlink_lines` se respeta para preservar el comportamiento
        # histórico cuando se invoca desde un compute.
        if not self.env.context.get('skip_unlink_lines'):
            try:
                with self.env.cr.savepoint():
                    lines_to_delete = SaleCreditLines.search([
                        ('credit_id', 'in', self.ids),
                        '|', '|',
                        ('amount_paid_total', '=', 0.0),
                        ('state', 'in', ['pending', 'cancelled']),
                        ('state', '=', False),
                    ])
                    if lines_to_delete:
                        _logger.info(
                            "compute_loan: borrando %d líneas sin pagos para créditos %s",
                            len(lines_to_delete), self.ids,
                        )
                        lines_to_delete.unlink()
            except Exception as _e:
                _logger.exception(
                    "compute_loan: no se pudieron limpiar líneas previas "
                    "para créditos %s: %s",
                    self.ids, _e,
                )
        i = self.frequency_id.interval

        # H-C01: Proteger el recálculo completo. Si numpy_financial revienta
        # o algún `create` falla, NO se debe perder la tabla de amortización
        # ni los pagos aplicados. Se preserva el retorno `''` para no romper
        # el contrato con `_compute_campo_calculado` (Char field).
        try:
            return self._compute_loan_body(i)
        except Exception as _e:
            _logger.exception(
                "compute_loan: error recalculando tabla de amortización "
                "para créditos %s: %s",
                self.ids, _e,
            )
            return ''

    def _compute_loan_body(self, i):
        """Cuerpo puro del recálculo de amortización, separado para poder
        envolverlo en try/except sin contaminar la firma pública de
        ``compute_loan``."""
        SaleCreditLines = self.env['sale.credit.line']
        move_vals_list = []
        for sc in self:

            date_list = []
            date = self.date_start
            sc.amount_per_rate = 90
            principal = sc.amount_financed
            saldo = sc.amount_financed

            if sc.amount_to_pay:
                SaleCreditLines.create({'credit_id': sc.id,
                                        'count': 0,
                                        'expected_date_payment': date,
                                        'name': '%s - [0]' % sc.name,
                                        'partner_id': sc.partner_id.id,
                                        'amount_initial': sc.total_sold,
                                        'company_id': sc.company_id.id,
                                        'amount_capital': 0,
                                        'amount_interest': 0,
                                        'sale_id': sc.sale_id.id,

                                        'co_debtor_id': sc.co_debtor_id.id,
                                        'amount_interest_installments': str("%.2f" % 0) + " %",
                                        'amount_fixed': sc.amount_to_pay,
                                        'amount_residual': sc.amount_to_pay,
                                        'amount_final': abs(float(principal))
                                        })

            if sc.method == 'reducing':
                months = sc.installment_id.installments
                rate = sc.percent_interest / 100.00 if sc.percent_interest else 0
                per = np.arange(months) + 1
                ipmt = fn.ipmt(rate / 12, per, months, principal)
                ppmt = fn.ppmt(rate / 12, per, months, principal)
                pmt = fn.pmt(rate / 12, months, principal)
                if sc.method and principal and months:
                    if np.allclose(ipmt + ppmt, pmt):
                        for payment in per:
                            index = payment - 1
                            principal = principal + ppmt[index]
                            if self.frequency_id.type == 'month':
                                months_elapsed = int(payment * i)
                                date = self.date_start + \
                                    relativedelta(months=+months_elapsed)

                            elif self.frequency_id.type == 'year':
                                years_elapsed = int(payment * i)
                                date = self.date_start + \
                                    relativedelta(years=+years_elapsed)

                            elif self.frequency_id.type == 'week':
                                weeks_elapsed = int(payment * i)
                                date = self.date_start + timedelta(weeks=+weeks_elapsed)

                            elif self.frequency_id.type == 'day':
                                days_elapsed = int(payment * i)
                                date = self.date_start + \
                                    relativedelta(days=+days_elapsed)

                            SaleCreditLines.create({'credit_id': sc.id,
                                                    'count': payment,
                                                    'name': '%s - [%s]' % (self.name, payment),
                                                    'expected_date_payment': date,
                                                    'partner_id': sc.partner_id.id,
                                                    'amount_initial': (ppmt[index] * -1) + abs(principal),
                                                    'company_id': sc.company_id.id,
                                                    'amount_capital': (ppmt[index] * -1),
                                                    'amount_interest': (ipmt[index] * -1),
                                                    'co_debtor_id': sc.co_debtor_id.id,
                                                    'sale_id': sc.sale_id.id,

                                                    'amount_interest_installments': str("%.2f" % ((rate / 12) * 100)) + " %",
                                                    'amount_fixed': (ppmt[index] * -1) + (ipmt[index] * -1),
                                                    'amount_residual': (ppmt[index] * -1) + (ipmt[index] * -1),
                                                    'amount_final': abs(float(principal))})
                            saldo = saldo - (ppmt[index] * -1) + (ppmt[index] * -1)
                        sc.amount_per_rate = pmt * -1
                        sc.amount_total = saldo

            if sc.method == 'flat':

                saldo = sc.amount_financed
                rate = sc.percent_interest / 100 * principal if sc.percent_interest else 0
                time = float(sc.installment_id.installments) / 12
                months = sc.installment_id.installments
                per = np.arange(months) + 1
                each_month_payment = balance = 0.00
                if time:
                    balance = ((principal / time + rate) / 12) * \
                        sc.installment_id.installments
                    for each_term in per:
                        if self.frequency_id.type == 'month':
                            months_elapsed = int(each_term * i)
                            date = self.date_start + \
                                relativedelta(months=+months_elapsed)

                        elif self.frequency_id.type == 'year':
                            years_elapsed = int(each_term * i)
                            date = self.date_start + relativedelta(years=+years_elapsed)

                        elif self.frequency_id.type == 'week':
                            weeks_elapsed = int(each_term * i)
                            date = self.date_start + timedelta(weeks=+weeks_elapsed)

                        elif self.frequency_id.type == 'day':
                            days_elapsed = int(each_term * i)
                            date = self.date_start + \
                                relativedelta(days=+days_elapsed)

                        interest = principal / time + rate
                        each_month_payment = interest / 12
                        total_pay_amount = each_month_payment * sc.installment_id.installments
                        balance -= each_month_payment
                        monthly_interest = rate * time / sc.installment_id.installments
                        monthly_principal = principal / sc.installment_id.installments
                        show_rate = sc.percent_interest / 12 if sc.percent_interest > 0 else 0

                        SaleCreditLines.create({
                            'credit_id': sc.id,
                            'count': each_term,
                            'expected_date_payment': date,
                            'partner_id': sc.partner_id.id,
                            'amount_initial': saldo,
                            'company_id': sc.company_id.id,
                            'amount_capital': monthly_principal,
                            'amount_interest': monthly_interest,
                            'co_debtor_id': sc.co_debtor_id.id,
                            'sale_id': sc.sale_id.id,

                            'amount_interest_installments': str("%.2f" % show_rate) + " %",
                            'amount_fixed': monthly_interest + monthly_principal,
                            'amount_residual': monthly_interest + monthly_principal,
                            'amount_final': abs(float(balance))
                        })
                    sc.amount_per_rate = monthly_interest + monthly_principal
                    sc.amount_total

        self.date_end = date
        return ''

    @api.depends('credit_lines.state')
    def optimization_dinamic(self):
        today = fields.Date.today()
        for credit in self:
            if round(credit.total_sold, 2) == round(credit.credit_amount, 2) or credit.credit_Adeudado == 0:
                # Detectar transición a 'closed' para gatillar limpieza y trazabilidad
                # solo cuando realmente cambia de estado (no idempotente).
                was_closed = (credit.state == 'closed')
                credit.write({
                    'state': 'closed',
                    'closed_date': today,
                })
                credit.payment_status = 'paid'
                if not credit.invoice_sale:
                    credit.to_invoice = True
                if not was_closed:
                    credit._onclose_cleanup_insurance()
                    credit._onclose_cleanup_maintenance()
                    credit._onclose_close_commission_period()
                    credit._post_closed_audit_message(source='auto')
            else:
                credit.payment_status = 'in_payment'
            for record in credit.credit_lines:
                if record.amount_paid_total != 0:
                    record.date_payment = today
                    record.amount_paid = (record.amount_residual - record.amount_paid_total)
                    if record.amount_paid <= 0.1:
                        record.amount_paid = 0

                else:
                    record.amount_paid = record.amount_residual


    def backdated_counter(self):
        line = self.env['sale.credit.line'].search(
            [('state', '=', 'paid_overdue'), ('credit_id', '=', self.id)])
        self.payment_backdated = len(line)

    def action_view_credit_lines_backdated(self):
        '''
        This function returns an action that display existing
        '''
        creditlines = self.credit_lines
        action = self.env["ir.actions.actions"]._for_xml_id(
            "cjg_finance.sale_credit_line_action")
        if creditlines:
            if len(creditlines) > 1:
                action['domain'] = [('id', 'in', creditlines.ids),
                                    ('state', '=', 'paid_overdue')]
            elif creditlines:
                form_view = [
                    (self.env.ref('cjg_finance.sale_credit_line_view_form').id, 'form')]
                if 'views' in action:
                    action['views'] = form_view + \
                        [(state, view)
                         for state, view in action['views'] if view != 'form']
                else:
                    action['views'] = form_view
                action['res_id'] = creditlines.id
            action['context'] = dict(
                self._context, default_partner_id=self.partner_id.id, default_credit_id=self.id)
            return action

    def action_archived_solicitud(self):
        archived_solicitud_ids = self.with_context(
            active_test=False).archived_product_ids
        action = self.env["ir.actions.actions"]._for_xml_id(
            "cjg_finance.sale_credit_action")
        action['domain'] = [('id', 'in', archived_solicitud_ids.ids),
                            ('active', '=', False)]
        action['context'] = dict(literal_eval(
            action.get('context')), search_default_inactive=True)
        return action

    def _compute_archived(self):
        archived_product_ids = self.env['sale.credit.line'].search(
            [('active', '=', False)])
        for order in self:
            products = archived_product_ids.filtered(
                lambda p: p.id in order.order_line.product_id.ids)
            order.archived_product_ids = [(6, 0, products.ids)]
            order.archived_product_count = len(products)

    def _credit_pay(self):
        payment = []
        for record in self.credit_lines:
            if record.amount_paid_total != 0:
                payment.append(record.amount_paid_total)

        # Check if any payments exist by looking at credit_lines
        has_payments = any(line.amount_paid_total > 0 for line in self.credit_lines)
        
        if has_payments:
            self.payment_status = 'in_payment'
        elif self.state == 'cancelled' and not has_payments:
            self.payment_status = 'cancel'
        else:
            self.payment_status = 'not_paid'
        if self.state == "closed":
            self.payment_status = 'paid'

        self.credit_amount = round(sum(payment), 2)

    def calculate_currency(self):
        for rate in self.currency_id_money:
            if self.origin == 'standard':
                origin_price = self.loan_amount
            else:
                origin_price = self.product_id.list_price

            fecha_mayor = datetime.date(1900, 1, 1)
            for i in rate.rate_ids:
                if len(rate.rate_ids) > 1:
                    if i.name > fecha_mayor:
                        fecha_mayor = i.name
                else:
                    fecha_mayor = i.name

            for i in rate.rate_ids:

                if rate.name == 'DOP':
                    if i.name == fecha_mayor:
                        total_sold = origin_price * i.inverse_company_rate
                        min_pay = total_sold * (self.percent_financing / 100)
                        self.write({
                            'total_sold': total_sold,
                            'min_amount': total_sold - min_pay,
                            'amount_to_pay': total_sold - min_pay,
                            'amount_financed': total_sold - self.amount_to_pay
                        })

                else:
                    if i.name == fecha_mayor:
                        total_sold = origin_price / i.inverse_company_rate
                        min_pay = total_sold * (self.percent_financing / 100)
                        self.write({
                            'total_sold': total_sold,
                            'min_amount': total_sold - min_pay,
                            'amount_to_pay': total_sold - min_pay,
                            'amount_financed': total_sold - self.amount_to_pay

                        })

    @api.onchange('company_id', 'currency_id_money')
    def onchange_currency_id(self):
        if self.currency_id_money:
            if self.currency_id_money != self.company_id.currency_id:
                self.active_manual_currency_rate = True
            else:
                self.active_manual_currency_rate = False
        else:
            self.active_manual_currency_rate = False

    @api.depends('currency_id_money')
    def _compute_currency_rate(self):
        for record in self:

            fecha_mayor = datetime.date(1900, 1, 1)
            for rate in record.currency_id_money:
                for i in rate.rate_ids:
                    if len(rate.rate_ids) > 1:
                        if i.name > fecha_mayor:
                            fecha_mayor = i.name
                    else:
                        fecha_mayor = i.name
                for i in rate.rate_ids:
                    if i.name == fecha_mayor:
                        record.computed_currency_rate = i.inverse_company_rate
                self.manual_currency_exchange_rate = record.computed_currency_rate

    @api.onchange('currency_id_money', 'apply_manual_currency_exchange', 'manual_currency_exchange_rate')
    def _calculate_manual_currency(self):

        if self.apply_manual_currency_exchange == False:
            self.calculate_currency()

        else:
            if self.origin == 'standard':
                origin_price = self.loan_amount
                
            else:
                origin_price = self.product_id.list_price

            for rate in self.currency_id_money:
                fecha_mayor = datetime.date(1900, 1, 1)
                for i in rate.rate_ids:
                    if len(rate.rate_ids) > 1:
                        if i.name > fecha_mayor:
                            fecha_mayor = i.name

                    else:
                        fecha_mayor = i.name

                for i in rate.rate_ids:
                    if rate.name == 'DOP':
                        self.apply_manual_currency_exchange = False
                        total_sold = origin_price
                        total_sold = origin_price * i.inverse_company_rate

                        min_pay = total_sold * (self.percent_financing / 100)
                        self.write({
                            'total_sold': total_sold,
                            'min_amount': total_sold - min_pay,
                            'amount_to_pay': total_sold - min_pay,
                            'amount_financed': total_sold - self.amount_to_pay
                        })
                    if i.name == fecha_mayor:
                        new_currency = i.inverse_company_rate

                    if self.apply_manual_currency_exchange == False:
                        total_sold = origin_price

                    elif self.apply_manual_currency_exchange == True and self.manual_currency_exchange_rate == 0:

                        self.write({
                            'manual_currency_exchange_rate': new_currency
                        })

                        total_sold = origin_price / self.manual_currency_exchange_rate

                    elif self.apply_manual_currency_exchange == True and self.manual_currency_exchange_rate > 0:
                        total_sold = origin_price / self.manual_currency_exchange_rate

                    min_pay = total_sold * (self.percent_financing / 100)
                    self.write({
                        'total_sold': total_sold,
                        'min_amount': total_sold - min_pay,
                        'amount_to_pay': total_sold - min_pay,
                        'amount_financed': total_sold - self.amount_to_pay,
                    })
                    
    @api.depends('credit_lines.amount_residual')
    def _credit_Adeudado(self):
        for credit in self:
            # Calcular el total adeudado como la suma de los residuales de todas las líneas
            total_adeudado = sum(
                line.amount_residual
                for line in credit.credit_lines
                if line.state != 'cancel'
            )
            credit.credit_Adeudado = round(total_adeudado, 2)
        
    @api.onchange('customize')
    def action_customize_finance(self):
        self.credit_lines

    @api.onchange('sale_id')
    def action_sale(self):
        pass

    @api.onchange('frequency_id')
    def onchange_loan_type_id(self):
        return {'domain': {'installment_id': [
            ('id',
             'in',
             self.mapped('frequency_id.installment_ids').ids
             )]
        }
        }

    @api.onchange('date_end')
    def date_end_change(self):

        fecha_n = self.date_end
        fecha_line = self.credit_lines
        fecha_ls = []

        if fecha_n != False:
            for record in fecha_line:
                fecha_ls.append(record.expected_date_payment)
            if fecha_ls[-2] < fecha_n:
                selfina = self.env['sale.credit.line'].search(
                    [('count', '=', int(len(fecha_ls) - 1))])
                selfina.write({'expected_date_payment': fecha_n})

            else:
                raise ValidationError(
                    _(
                        f"La fecha no debe ser menor  a la cuota N{len(fecha_line)-1} {fecha_ls[-1]}"
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            company_id = vals.get('company_id') or self.env.company.id
            if not vals.get('name') or vals.get('name') in ('New', '/'):
                seq_date = None
                if 'date_contract' in vals:
                    seq_date = fields.Datetime.context_timestamp(
                        self, fields.Datetime.to_datetime(vals['date_contract']))
                vals['name'] = self.env['ir.sequence'].with_company(
                    company_id).next_by_code('sale.credit', sequence_date=seq_date) or '/'
            if vals.get('contract_process_type') == 'reactivation' and not vals.get('reactivation_penalty_rate'):
                vals['reactivation_penalty_rate'] = 30.0
        return super(SaleCredit, self).create(vals_list)

    @api.model
    def _get_origin_reactivation_count(self, credit):
        count = 0
        visited = set()
        current = credit
        while current and current.id and current.id not in visited:
            visited.add(current.id)
            if current.contract_process_type == 'reactivation':
                count += 1
            current = current.origin_credit_id
        return count

    def _get_process_paid_breakdown(self):
        self.ensure_one()
        payment_lines = self.env['sale.credit.payment.line'].sudo().search([
            ('sale_payment_id.credit_id', '=', self.id),
            ('state', '!=', 'cancelled'),
        ])
        capital_paid = (self.initial_payment_total or 0.0) + sum(payment_lines.mapped('amount_capital'))
        interest_paid = sum(payment_lines.mapped('amount_interest'))
        return capital_paid, interest_paid

    def _get_process_product_type(self):
        self.ensure_one()
        if getattr(self, 'crm_lead_id', False) and self.crm_lead_id.product_type:
            return self.crm_lead_id.product_type
        if getattr(self, 'funeral_service_id', False):
            return 'service'
        return 'property' if self.product_id else False

    def _is_process_improvement_eligible(self):
        self.ensure_one()
        if self.state == 'closed':
            return True
        return self.state in ('approved', 'active') and not self.has_overdue

    def _get_process_reference_amount(self):
        self.ensure_one()
        lead = getattr(self, 'crm_lead_id', False)
        if lead and lead.price_dop:
            return lead.price_dop
        return self.total_sold or 0.0

    def _get_process_pending_installments(self):
        self.ensure_one()
        pending_lines = self.credit_lines.filtered(
            lambda line: line.count and line.state not in ('paid', 'cancelled') and (line.amount_residual or line.amount_fixed)
        )
        return len(pending_lines)

    def _get_process_state_label(self):
        self.ensure_one()
        if self.process_detail_status and self.process_detail_status != 'normal':
            return dict(self._fields['process_detail_status'].selection).get(
                self.process_detail_status,
                self.process_detail_status,
            )
        return dict(self._fields['state'].selection).get(self.state, self.state or '')

    def _get_reactivation_candidate_lines(self):
        self.ensure_one()
        return self.credit_lines.filtered(
            lambda line: line.count >= 1
            and line.state not in ('paid', 'cancelled')
            and (line.amount_residual or 0.0) > 0
        ).sorted('count')

    def _distribute_amount_by_lines(self, amount, lines):
        self.ensure_one()
        if not lines:
            return {}

        currency = self.currency_id_money or self.currency_id or self.env.company.currency_id
        total_amount = currency.round(amount or 0.0)
        if not total_amount:
            return {line.id: 0.0 for line in lines}

        base_share = currency.round(total_amount / len(lines))
        distributed = {}
        assigned = 0.0
        for index, line in enumerate(lines, start=1):
            if index == len(lines):
                share = total_amount - assigned
            else:
                share = base_share
                assigned += share
            distributed[line.id] = share
        return distributed

    def _recompute_pending_line_balances(self, lines):
        self.ensure_one()
        ordered_lines = lines.sorted('count')
        remaining_balance = sum(ordered_lines.mapped('amount_residual'))
        write_ctx = dict(self.env.context, allow_reactivation_transition=True)
        for line in ordered_lines:
            opening_balance = remaining_balance
            remaining_balance -= (line.amount_residual or 0.0)
            line.with_context(write_ctx).write({
                'amount_initial': opening_balance,
                'amount_final': max(remaining_balance, 0.0),
            })

    def _mark_as_cancelled_by_process(self, detail_status, notes=None):
        self.ensure_one()
        if detail_status not in ('anulado_mejora', 'anulado_devolucion'):
            raise ValidationError(_('El detalle de cancelación indicado no es válido.'))

        pending_lines = self.credit_lines.filtered(
            lambda line: line.state not in ('paid', 'cancelled')
        )

        self.write({
            'state': 'cancelled',
            'process_detail_status': detail_status,
        })
        if pending_lines and detail_status == 'anulado_mejora':
            pending_lines.cancel_credit_lines()

        detail_label = dict(self._fields['process_detail_status'].selection).get(detail_status, detail_status)
        message_body = _(
            "<p><strong>Contrato marcado como %(detail)s</strong></p>"
        ) % {'detail': detail_label}
        if detail_status == 'anulado_devolucion':
            message_body += _("<p>Se preservó el plan pendiente para permitir una futura reactivación del mismo contrato.</p>")
        if notes:
            message_body += _("<p>Detalle: %(notes)s</p>") % {'notes': notes}
        self.message_post(
            body=message_body,
            subject=detail_label,
        )
        return True

    def _reactivate_same_contract(self, penalty_rate, notes=None):
        self.ensure_one()
        penalty_rate = penalty_rate or 0.0
        if penalty_rate < 0:
            raise ValidationError(_('La penalidad de reactivación no puede ser negativa.'))

        candidate_lines = self._get_reactivation_candidate_lines()
        if not candidate_lines:
            raise ValidationError(_(
                'El contrato %s no tiene cuotas pendientes disponibles para reactivar.'
            ) % self.name)

        if self.state not in ('withdrawn', 'desistido', 'cancelled'):
            raise ValidationError(_(
                'Solo se pueden reactivar directamente contratos desistidos o anulados.'
            ))

        paid_capital, _paid_interest = self._get_process_paid_breakdown()
        if paid_capital <= 0:
            raise ValidationError(_(
                'El contrato %s no tiene capital pagado para calcular la penalidad de reactivación.'
            ) % self.name)

        currency = self.currency_id_money or self.currency_id or self.env.company.currency_id
        penalty_amount = currency.round((paid_capital or 0.0) * ((penalty_rate or 0.0) / 100.0))
        distributed_amounts = self._distribute_amount_by_lines(penalty_amount, candidate_lines)
        write_ctx = dict(self.env.context, allow_reactivation_transition=True)

        for line in candidate_lines:
            share = distributed_amounts.get(line.id, 0.0)
            vals = {'state': 'pending'}
            if share:
                vals.update({
                    'amount_others': (line.amount_others or 0.0) + share,
                    'amount_fixed': (line.amount_fixed or 0.0) + share,
                    'amount_residual': (line.amount_residual or 0.0) + share,
                })
            line.with_context(write_ctx).write(vals)

        self._recompute_pending_line_balances(candidate_lines)
        self.with_context(write_ctx).write({
            'state': 'approved',
            'contract_process_type': 'reactivation',
            'reactivation_penalty_rate': penalty_rate,
            'reactivation_penalty_amount': penalty_amount,
            'reactivation_penalty_distributed': True,
            'process_detail_status': 'reactivado',
        })

        detail_lines = [
            _('<p><strong>Contrato reactivado directamente</strong></p>'),
            _('<p>Capital pagado reconocido: %(amount).2f</p>') % {'amount': paid_capital},
            _('<p>Penalidad aplicada (%(rate).2f%%): %(amount).2f</p>') % {
                'rate': penalty_rate,
                'amount': penalty_amount,
            },
            _('<p>Cuotas afectadas: %(count)s</p>') % {'count': len(candidate_lines)},
        ]
        if notes:
            detail_lines.append(_('<p>Detalle: %(notes)s</p>') % {'notes': notes})
        self.message_post(
            body=''.join(detail_lines),
            subject=_('Reactivación Directa'),
        )
        return True

    @api.depends(
        'state',
        'has_overdue',
        'initial_payment_total',
        'credit_lines.state',
        'credit_lines.amount_residual',
        'credit_lines.amount_fixed',
        'credit_payments.credit_payment_lines.amount_capital',
        'credit_payments.credit_payment_lines.amount_interest',
        'credit_payments.credit_payment_lines.state',
        'contract_process_type',
        'origin_credit_id',
        'crm_lead_id',
        'total_sold',
        'discount_amount',
        'process_detail_status',
    )
    def _compute_process_origin_metrics(self):
        for record in self:
            capital_paid, interest_paid = record._get_process_paid_breakdown()
            record.process_capital_paid = capital_paid
            record.process_interest_paid = interest_paid
            record.process_pending_installments = record._get_process_pending_installments()
            record.process_state_label = record._get_process_state_label()
            record.process_default_penalty_rate = 30.0
            record.process_product_type = record._get_process_product_type()
            record.process_reference_amount = record._get_process_reference_amount()
            record.process_improvement_eligible = record._is_process_improvement_eligible()

    def _get_final_sale_line_values(self):
        self.ensure_one()
        line_values = []

        if 'property_product_ids' in self._fields and self.property_product_ids:
            for property_rec in self.property_product_ids:
                template = property_rec.product_id
                variant = template.product_variant_id if template else False
                price = property_rec.price or (template.list_price if template else 0.0) or 0.0
                if variant:
                    line_values.append((0, 0, {
                        'product_id': variant.id,
                        'product_uom_qty': 1.0,
                        'price_unit': price,
                        'name': property_rec.display_name or property_rec.name,
                    }))

        if not line_values and 'service_product_ids' in self._fields and self.service_product_ids:
            for service in self.service_product_ids:
                variant = service.product_variant_id if service._name == 'product.template' else service
                price = getattr(service, 'list_price', False) or getattr(service, 'lst_price', False) or 0.0
                if variant:
                    line_values.append((0, 0, {
                        'product_id': variant.id,
                        'product_uom_qty': 1.0,
                        'price_unit': price,
                        'name': variant.display_name,
                    }))

        if not line_values and self.product_id:
            line_values.append((0, 0, {
                'product_id': self.product_id.id,
                'product_uom_qty': 1.0,
                'price_unit': self.total_sold or self.amount_total or 0.0,
                'name': self.product_id.display_name,
            }))

        if not line_values:
            raise UserError(_('No se encontró un producto válido para generar la factura final del contrato.'))

        return line_values

    def _ensure_final_sale_order(self):
        self.ensure_one()
        if self.sale_id:
            return self.sale_id

        sale_order = self.env['sale.order'].create({
            'credit_id': self.id,
            'sale_advanced': True,
            'partner_id': self.partner_id.id,
            'order_line': self._get_final_sale_line_values(),
        })
        self.sale_id = sale_order.id
        self.sale_valid = True
        for line in self.credit_lines:
            line.sale_id = sale_order.id
        return sale_order

    def action_to_closed(self):
        if round(self.total_sold, 2) == round(self.credit_amount, 2):
            today = fields.Date.today()
            self.write({
                'state': 'closed',
                'closed_date': today,
            })
            if not self.invoice_sale:
                self.to_invoice = True
            # Limpieza en cascada al cerrar (GAP-12.04, 12.05, 12.06)
            self._onclose_cleanup_insurance()
            self._onclose_cleanup_maintenance()
            self._onclose_close_commission_period()
            # Trazabilidad (GAP-12.10)
            self._post_closed_audit_message(source='manual')
        else:
            raise ValidationError(
                _(
                    "No se puede puede mover a completado hasta que Total Adeudado sea igual 0."
                )
            )

    # ============================================================
    # GAP-12.04 / 12.05 / 12.06 / 12.10
    # Helpers de cierre: limpieza en cascada + trazabilidad.
    # Se invocan desde action_to_closed() y optimization_dinamic().
    # Todos son idempotentes y tolerantes a ausencia de registros.
    # ============================================================

    def _onclose_cleanup_insurance(self):
        """GAP-12.04: desactiva los seguros del contrato al cerrarlo.

        Para cada ``credit.insurance`` vinculado al contrato:
        - Marca ``life_insurance_active=False`` y ``debt_forgiveness_active=False``.
        - Setea ``life_insurance_end`` y ``debt_forgiveness_end`` al día de hoy.
        - Deja una nota en el chatter del seguro.

        ``is_eligible`` es compute, así que se controla la elegibilidad mediante
        los flags ``*_active``. Si no hay seguros, retorna sin error.
        """
        self.ensure_one()
        Insurance = self.env['credit.insurance']
        insurances = Insurance.search([('credit_id', '=', self.id)])
        if not insurances:
            return 0
        today = fields.Date.today()
        for ins in insurances:
            vals = {
                'life_insurance_active': False,
                'debt_forgiveness_active': False,
            }
            if ins.life_insurance_end is False or ins.life_insurance_end > today:
                vals['life_insurance_end'] = today
            if ins.debt_forgiveness_end is False or ins.debt_forgiveness_end > today:
                vals['debt_forgiveness_end'] = today
            ins.write(vals)
            ins.message_post(
                body=_(
                    "Seguro desactivado por cierre del contrato %s. "
                    "Vigencia de vida y condonación cerradas al %s."
                ) % (self.name, today),
                subject=_('Cierre de Seguro — Contrato %s') % self.name,
            )
        _logger.info(
            "GAP-12.04: contrato %s — %s seguros desactivados al cerrar.",
            self.name, len(insurances),
        )
        return len(insurances)

    def _onclose_cleanup_maintenance(self):
        """GAP-12.05: exonera los contratos de mantenimiento del crédito.

        Para cada ``maintenance.contract`` con ``sale_credit_id == self.id``:
        - Si el modelo expone ``action_cancel`` o permite ``state='exonerated'``,
          se aplica el más limpio. ``maintenance.contract`` ya implementa la
          transición directa a ``exonerated`` (línea 337 de su modelo).
        - Si no hay mantenimiento, retorna sin error.
        """
        self.ensure_one()
        Maintenance = self.env['maintenance.contract']
        contracts = Maintenance.search([('sale_credit_id', '=', self.id)])
        if not contracts:
            return 0
        for m in contracts:
            try:
                if hasattr(m, 'action_cancel') and callable(m.action_cancel):
                    m.action_cancel()
                else:
                    m.write({'state': 'exonerated'})
            except Exception as exc:  # noqa: BLE001
                # No rompemos el cierre si un mantenimiento específico falla.
                _logger.warning(
                    "GAP-12.05: no se pudo exonerar mantenimiento %s del contrato %s: %s",
                    m.name, self.name, exc,
                )
                continue
            m.message_post(
                body=_("Mantenimiento exonerado por cierre del contrato %s.") % self.name,
                subject=_('Exoneración Mantenimiento — Contrato %s') % self.name,
            )
        _logger.info(
            "GAP-12.05: contrato %s — %s mantenimientos exonerados al cerrar.",
            self.name, len(contracts),
        )
        return len(contracts)

    def _onclose_close_commission_period(self):
        """GAP-12.06: cierra los períodos de comisión que incluyen el contrato.

        Busca ``commission.period`` cuyo rango de fechas cubra ``date_start`` del
        contrato, en estado ``draft`` o ``preclosed`` (los demás se ignoran).
        Llama ``action_generate_close`` con try/except robusto: si la generación
        falla (p. ej. comisiones no conciliadas), se loguea como warning y el
        cierre del contrato continúa.

        No cierra períodos de meses donde el contrato no aplica: el filtro por
        rango ``sales_start_date``/``close_date`` y por estado abierto es la
        salvaguarda.
        """
        self.ensure_one()
        Period = self.env['commission.period']
        if not self.date_start:
            return 0
        periods = Period.search([
            ('state', 'in', ['draft', 'preclosed']),
            ('sales_start_date', '<=', self.date_start),
            ('close_date', '>=', self.date_start),
        ])
        if not periods:
            return 0
        closed = 0
        for period in periods:
            try:
                period.action_generate_close()
                closed += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "GAP-12.06: no se pudo cerrar período %s al cerrar contrato %s: %s",
                    period.name, self.name, exc,
                )
                continue
            self.message_post(
                body=_(
                    "Período de comisiones '%s' liquidado por cierre del contrato."
                ) % period.name,
                subject=_('Cierre Comisión — Contrato %s') % self.name,
            )
        _logger.info(
            "GAP-12.06: contrato %s — %s/%s períodos de comisión cerrados.",
            self.name, closed, len(periods),
        )
        return closed

    def _post_closed_audit_message(self, source='manual'):
        """GAP-12.10: message_post enriquecido en el cierre del contrato.

        ``source`` admite:
        - ``'manual'``: botón "Completado" desde el form (``action_to_closed``).
        - ``'auto'``: cierre automático al pagar la última cuota
          (``optimization_dinamic``).
        - ``'forgiveness'``: condonación de deuda (queda registrado desde el
          wizard, no desde aquí).
        """
        self.ensure_one()
        user = self.env.user
        source_label = {
            'manual': 'manual',
            'auto': 'automático (pago de última cuota)',
        }.get(source, source)
        body = _(
            "<p><strong>Cierre de Contrato</strong> (%s)</p>"
            "<ul>"
            "<li><strong>Usuario:</strong> %s</li>"
            "<li><strong>Fecha:</strong> %s</li>"
            "<li><strong>Monto total:</strong> %s</li>"
            "<li><strong>Monto pagado:</strong> %s</li>"
            "<li><strong>Balance final:</strong> %s</li>"
            "<li><strong>Motivo:</strong> Saldo completado — contrato saldado</li>"
            "</ul>"
        ) % (
            source_label,
            user.name,
            self.closed_date or fields.Date.today(),
            self.total_sold or 0.0,
            self.credit_amount or 0.0,
            self.credit_Adeudado or 0.0,
        )
        self.message_post(
            body=body,
            subject=_('Cierre de Contrato'),
        )

    def action_print_finiquito(self):
        """GAP-12.07: lanza el reporte QWeb 'Acta de Cierre / Finiquito'."""
        self.ensure_one()
        if self.state != 'closed':
            raise UserError(_(
                "Solo se puede imprimir el finiquito de contratos en estado "
                "'closed' (completado). Estado actual: %s."
            ) % self.state)
        return self.env.ref(
            'cjg_finance.action_report_sale_credit_finiquito'
        ).report_action(self)

    def action_back_to_draft(self):
        pass

    def action_create_sale(self):
        if self.sale_id:
            raise ValidationError(
                _(
                    "La Venta ya esta asociada a una solicitud de prestamo, por favor revisar el numero de la venta"
                )
            )
        sale_order = self._ensure_final_sale_order()

        return {
            'name': 'Nueva Venta',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }

    def action_back_to_requested(self):
        pass

    def action_request_credit(self):
        if bool(self.credit_lines) == False:
            raise ValidationError(
                _(
                    "Por favor haga click en Calculate"
                )
            )
        else:
            if self.refinance_active == True:
                self.action_approve_credit()
            else:
                self.state = "requested"

    def action_send_credit(self):
        pass

    def action_send_contract(self):
        pass

    def action_approve_credit(self):
        self.state = "approved"
        # Post-approval process logic
        for credit in self:
            if credit.contract_process_type == 'reactivation' and credit.origin_credit_id:
                credit._distribute_reactivation_penalty()
                credit.origin_credit_id.write({'process_detail_status': 'reactivado'})
                credit.write({'process_detail_status': 'reactivado'})
                credit._post_origin_summary_to_chatter()
            elif credit.contract_process_type == 'improvement' and credit.origin_credit_id:
                credit.origin_credit_id.write({
                    'state': 'cancelled',
                    'process_detail_status': 'anulado_mejora',
                })
                credit._post_origin_summary_to_chatter()

    def _distribute_reactivation_penalty(self):
        """
        Distribuye reactivation_penalty_amount entre las cuotas pendientes
        en el campo 'amount_others' (OTROS) de cada sale.credit.line.
        """
        self.ensure_one()
        if (
            not self.reactivation_penalty_amount
            or self.contract_process_type != 'reactivation'
            or self.reactivation_penalty_distributed
        ):
            return

        pending_lines = self.credit_lines.filtered(
            lambda l: l.state in ('pending', 'paid_overdue')
        ).sorted('expected_date_payment')

        if not pending_lines:
            return

        n = len(pending_lines)
        currency = self.currency_id_money or self.currency_id or self.env.company.currency_id
        penalty_per_line = currency.round(self.reactivation_penalty_amount / n)
        remainder = currency.round(
            self.reactivation_penalty_amount - (penalty_per_line * n)
        )

        for i, line in enumerate(pending_lines):
            extra = remainder if i == 0 else 0.0
            line_penalty = penalty_per_line + extra
            line.write({
                'amount_others': (line.amount_others or 0.0) + line_penalty,
                'amount_fixed': (line.amount_fixed or 0.0) + line_penalty,
                'amount_residual': (line.amount_residual or 0.0) + line_penalty,
            })

        self.write({'reactivation_penalty_distributed': True})

        self.message_post(
            body=_('Penalidad de reactivación distribuida: %s total, %s por cuota en %d cuotas.') % (
                self.reactivation_penalty_amount, penalty_per_line, n
            )
        )

    def _post_origin_summary_to_chatter(self):
        """
        Copia al chatter del contrato derivado un resumen del contrato origen.
        """
        self.ensure_one()
        if not self.origin_credit_id:
            return
        origin = self.origin_credit_id
        self.message_post(
            body=_(
                'Contrato derivado de: <b>%s</b><br/>'
                'Capital pagado origen: %s<br/>'
                'Interés pagado origen: %s<br/>'
                'Fecha de inicio origen: %s'
            ) % (
                origin.name,
                origin.process_capital_paid,
                origin.process_interest_paid,
                origin.date_start,
            )
        )

    def action_follow_credit_flow(self):
        self.ensure_one()
        if self.state != 'closed':
            raise UserError(_('La facturación final solo está disponible cuando el contrato está saldado/cerrado.'))

        sale_order = self._ensure_final_sale_order()
        if sale_order.state in ('draft', 'sent'):
            sale_order.action_confirm()

        invoices = sale_order.invoice_ids.filtered(lambda inv: inv.state != 'cancel')
        if not invoices:
            invoices = sale_order._create_invoices()
            invoices.action_post()

        invoice = invoices[:1]
        if invoice:
            self.write({
                'invoice_sale': invoice.id,
                'invoice_ids': invoice.id,
                'to_invoice': False,
            })
            return {
                'name': _('Factura Final'),
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': invoice.id,
                'view_mode': 'form',
                'target': 'current',
            }

        raise UserError(_('No se pudo generar la factura final del contrato.'))

    def action_refuse_credit(self):
        wizard = self.env['sale.credit.refuse.wizard']

        return {
            'name': "¿ Seguro que deseas rechazar la solicitud de credito ?",
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.refuse.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
    def action_refinance_credit(self):
        wizard = self.env['sale.credit.refinance.wizard']

        return {
            'name': "¿ Seguro que deseas refinanciar la solicitud de credito ?",
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.refinance.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }
    def action_tasa_credit(self):
        wizard = self.env['sale.credit.personalizacion.wizard']

        return {
            'name': "Personalizar cuota",
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.personalizacion.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_back_to_approved(self):
        pass

    def action_transfer_credit(self):
        wizard = self.env['sale.credit.transfer.wizard']
        # wizard.write({'partner_id':self.partner_id.id})
        return {
            'name': "¿ Seguro que deseas traspasar la solicitud de credito ?",
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.transfer.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_cancel_credit(self):
        wizard = self.env['sale.credit.cancel.wizard']

        return {
            'name': "¿ Seguro que deseas cancelar solicitud de credito ?",
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.cancel.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_open_reactivation_wizard(self):
        """Open the reactivation wizard for this contract."""
        self.ensure_one()
        if self.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para reactivación. '
                'Solo contratos en estado Anulado o Desistido pueden ser reactivados.'
            ) % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reactivar Contrato'),
            'res_model': 'sale.credit.reactivation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_open_reembolso_wizard(self):
        """Open the 70/30 refund wizard for contracts cancelled/withdrawn 12+ months ago."""
        self.ensure_one()
        if self.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para reembolso 70/30. '
                'Solo contratos en estado Anulado o Desistido pueden '
                'solicitar reembolso. Estado actual: %s'
            ) % (self.name, self.state))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reembolso 70/30 (12+ meses)'),
            'res_model': 'sale.credit.reembolso.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_open_no_reembolso_wizard(self):
        """Open the 'No Solicitar Reembolso' wizard (Opcion 2 con solicitud escrita).

        Replica el procedimiento del documento 'Proceso reactivacion y Mejora'
        (parrafos 23 y 180): el cliente decide por escrito NO solicitar
        reembolso ni NC; el monto pagado queda en los ingresos de la empresa.

        El wizard reutiliza los campos ``no_refund_*`` ya existentes en el
        modelo (manteniendo una sola fuente de verdad con el badge del form
        y con ``action_register_no_refund``).
        """
        self.ensure_one()
        if self.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                "Solo se puede registrar 'No solicitar reembolso' para "
                "contratos en estado Anulado o Desistido. "
                "Contrato %s en estado: %s."
            ) % (self.name, self.process_state_label or self.state))
        if self.no_refund_registered:
            raise UserError(_(
                "El contrato %s ya tiene registrada la decision de NO "
                "reembolso. No se puede abrir el wizard nuevamente."
            ) % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('No Solicitar Reembolso'),
            'res_model': 'sale.credit.no.reembolso.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    @api.depends('derived_credit_ids')
    def _compute_derived_credit_count(self):
        for record in self:
            record.derived_credit_count = len(record.derived_credit_ids)

    def action_view_derived_credits(self):
        """Navigate to derived contracts from origin contract."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contratos Derivados'),
            'res_model': 'sale.credit',
            'view_mode': 'tree,form',
            'domain': [('origin_credit_id', '=', self.id)],
            'context': {'default_origin_credit_id': self.id},
        }

    def cancelled(self):
        self.state = 'cancelled'
        self.credit_lines.cancel_credit_lines()
        self.credit_payments.mapped('credit_payment_lines').cancel_payment_lines()

    def refuse(self):
        self.state = 'refuse'
        self.sale_id = False

    # ============================================================
    # OWNERSHIP HELPERS — SPRINT COBROS-CRITICOS 2026-06-20
    # ============================================================
    # El modelo tiene DOS campos relacionados con oficiales de cobro:
    #   - oficial_id        (definido en este archivo, "Oficial de Cuenta")
    #   - collection_user_id (definido en cjg_finance_collection/models/sale_credit_inherit.py,
    #                          "Oficial de Cobro" — string distinto, mismo propósito)
    #
    # Distintos lugares del código usaban uno u otro, causando duplicación
    # de comisiones (C-05) y métricas infladas. Decisión Jeffry 2026-06-20:
    # helper unificado `_get_collection_officer()` con prioridad a oficial_id,
    # fallback a collection_user_id.
    #
    # NO se borra ninguno de los dos campos (compatibilidad hacia atrás y
    # porque el módulo cjg_finance_services los usa para portfolio_reassignment
    # con semántica distinta: "oficial de mantenimiento").
    #
    # Migrar gradualmente las llamadas directas al helper. Por ahora se migran
    # los 3 puntos críticos:
    #   1. collection_acta_cierre._debitar_comisiones
    #   2. collection_requerimiento.oficial_id (related)
    #   3. collection_solicitud_gestion._re_add_to_meta

    def _get_collection_officer(self):
        """Devuelve el oficial responsable del cobro de este contrato.

        Prioridad:
          1. self.oficial_id (Oficial de Cuenta) — fuente primaria
          2. self.collection_user_id (Oficial de Cobro) — fallback
          3. None si ninguno está asignado

        Usar SIEMPRE este helper en lugar de acceder a los campos
        directamente. Mantiene una única fuente de verdad para "quién cobra".
        """
        self.ensure_one()
        return self.oficial_id or self.collection_user_id or False

    def _get_collection_officer_for_records(records):
        """Variante para recordset. Devuelve dict {credit_id: officer_id}."""
        result = {}
        for rec in records:
            officer = rec.oficial_id or rec.collection_user_id
            if officer:
                result[rec.id] = officer
        return result

    def update_related_payments(self):
        related_payments = self.env['sale.credit.payment'].search([('credit_id', '=', self.id)])
        for payment in related_payments:
            payment.onchange_credit_id()
            
    def write(self, vals):
        """Sobrescritura de ``write`` con tres responsabilidades:

        1. **GAP-12.03 — validación de la máquina de estados (H-C07)**: si la
           escritura incluye ``state`` y la transición no está permitida por
           ``_ALLOWED_STATE_TRANSITIONS``, se lanza ``UserError`` con un mensaje
           accionable. Use siempre las acciones del modelo
           (``action_to_closed``, ``action_cancel_credit``, etc.) en lugar de
           asignar ``state`` directamente.
        2. Refresco de pagos relacionados (``update_related_payments``) cuando
           cambian ``credit_lines`` o ``state``.
        3. Cancelación automática de cuotas pendientes cuando el contrato
           transiciona a un estado terminal por fallecimiento del titular
           (``inhumado``/``cremado``), replicando la lógica legacy de Testarossa.
        """
        # H-C07 / GAP-12.03: validar transición de state si se está cambiando
        if 'state' in vals:
            new_state = vals['state']
            for record in self:
                current = record.state
                if current == new_state:
                    continue
                allowed = self._ALLOWED_STATE_TRANSITIONS.get(current, set())
                if new_state not in allowed:
                    _logger.warning(
                        "Transición de estado no permitida: %s -> %s en contrato %s. "
                        "Estados válidos desde %s: %s",
                        current, new_state, record.name, current, allowed or '(ninguno, terminal)'
                    )
                    # GAP-12.03 (P0): la máquina de estados se valida en producción.
                    # Toda mutación directa de `state` por código que no pertenezca a
                    # las acciones del modelo (action_to_closed, action_cancel, etc.)
                    # rompe el contrato y debe corregirse en origen.
                    raise UserError(_(
                        "Transición inválida: %(old)s → %(new)s. "
                        "Use las acciones del modelo (action_to_closed, action_cancel, "
                        "action_cancel_credit, etc.) en lugar de asignar `state` "
                        "directamente. Estados válidos desde %(old_label)s: %(allowed)s"
                    ) % {
                        'old': current,
                        'new': new_state,
                        'old_label': current,
                        'allowed': ', '.join(sorted(allowed)) or '(ninguno, terminal)',
                    })
                # Transición a estado terminal por fallecimiento del titular
                # (Testarossa doPagoInhumacion: tipo_servicio INH/CRE → estatus terminal).
                if new_state in ('inhumado', 'cremado'):
                    pending = record.credit_lines.filtered(
                        lambda l: l.state not in ('paid', 'cancelled'))
                    _logger.info(
                        "Contrato %s transiciona a '%s' por fallecimiento del titular. "
                        "Bloqueando %s cuotas pendientes.",
                        record.name, new_state, len(pending))
        res = super(SaleCredit, self).write(vals)
        if 'credit_lines' in vals or 'state' in vals:
            self.update_related_payments()
        # Post-write: cancelar cuotas pendientes si el contrato pasa a estado terminal
        # por fallecimiento del titular. Esto replica la lógica de Testarossa que
        # bloquea el cobro de nuevas cuotas al pasar el contrato a Inhumado/Cremado.
        if 'state' in vals and vals['state'] in ('inhumado', 'cremado'):
            for record in self:
                pending_lines = record.credit_lines.filtered(
                    lambda l: l.state not in ('paid', 'cancelled'))
                if pending_lines:
                    pending_lines.write({'state': 'cancelled'})
                    record.message_post(body=_(
                        "Contrato transiciona a estado '%s' por fallecimiento del titular. "
                        "%s cuotas pendientes canceladas automáticamente."
                    ) % (vals['state'], len(pending_lines)))
        return res

    # ============================================
    # REFINANCING VALIDATION METHODS
    # ============================================

    def _validate_no_pending_rcvs(self):
        """
        Valida que no existan RCVs (Recibos de Cobro Virtual) pendientes
        Basado en validación de Testarossa
        """
        self.ensure_one()
        
        # Verificar si el módulo RCV está instalado
        if 'sale.credit.rcv' not in self.env:
            return

        # Buscar RCVs pendientes para este crédito
        pending_rcvs = self.env['sale.credit.rcv'].search([
            ('credit_id', '=', self.id),
            ('state', 'in', ['draft', 'pending', 'approved'])
        ])
        
        if pending_rcvs:
            rcv_list = '\n'.join([f"- {rcv.name}" for rcv in pending_rcvs])
            raise UserError(_(
                "Este contrato tiene RCVs pendientes que deben procesarse "
                "o anularse antes de poder refinanciar:\n\n%s\n\n"
                "Por favor, complete o anule estos RCVs e intente nuevamente."
            ) % rcv_list)
    
    def _validate_overdue_balance(self):
        """
        Valida saldos vencidos según configuración del sistema
        Basado en validación de Testarossa
        """
        self.ensure_one()
        
        # Obtener configuración
        allow_overdue = self.env['ir.config_parameter'].sudo().get_param(
            'cjg_finance.refinance_allow_with_overdue', default='False'
        ) == 'True'
        
        # Si hay saldo vencido y no está permitido refinanciar con atrasos
        if self.overdue_amount > 0 and not allow_overdue:
            raise UserError(_(
                "El contrato tiene saldo vencido: %s %s\n\n"
                "Opciones:\n"
                "1. Regularice el pago antes de refinanciar, o\n"
                "2. Configure el sistema para permitir refinanciamiento con atrasos "
                "(Configuración → Créditos → Permitir Refinanciar con Saldo Vencido)"
            ) % (self.currency_id.symbol, '{:,.2f}'.format(self.overdue_amount)))
    
    def _validate_refinance_balance(self):
        """Valida que haya saldo pendiente para refinanciar"""
        self.ensure_one()
        
        if self.credit_Adeudado <= 0:
            raise UserError(_(
                "El crédito no tiene saldo pendiente para refinanciar.\n"
                "Saldo actual: %s %s"
            ) % (self.currency_id.symbol, '{:,.2f}'.format(self.credit_Adeudado)))

    # ============================================
    # REFINANCING CALCULATION METHODS
    # ============================================

    def _calc_refinance_penalty(self):
        """
        Calcula la penalización por refinanciamiento
        Basado en configuración del sistema (% del saldo actual)
        """
        self.ensure_one()
        penalty_rate = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'cjg_finance.refinance_penalty_rate', default='0.0'
            )
        )
        penalty = self.credit_Adeudado * (penalty_rate / 100.0)
        return penalty
    
    def _calc_new_interest(self, new_term, capital_down_payment=0.0):
        """
        Calcula los nuevos intereses para el refinanciamiento
        Basado en lógica de Testarossa:
        - Si nuevo plazo > actual: interés solo sobre diferencia
        - Si nuevo plazo < actual: recalcular total
        - Si plazo <= mínimo configurado: tasa 0%
        
        Args:
            new_term: Nuevo número de cuotas
            capital_down_payment: Monto de abono a capital
            
        Returns:
            float: Monto de intereses a generar
        """
        self.ensure_one()
        
        # Capital pendiente después del abono
        new_capital = self.credit_Adeudado - capital_down_payment
        
        if new_capital <= 0:
            return 0.0
        
        # Cuotas pendientes actuales (sin contar las pagadas)
        pending_installments = len(
            self.credit_lines.filtered(lambda l: l.state == 'pending')
        )
        
        # Diferencia de plazo
        term_difference = new_term - pending_installments
        
        # Verificar si aplica tasa 0 por plazo corto
        min_term_no_interest = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'cjg_finance.refinance_min_term_no_interest', default='0'
            )
        )
        
        if new_term <= min_term_no_interest:
            return 0.0
        
        # Obtener tasa de interés mensual
        interest_rate = self.category_id.interest_rate / 100.0 / 12.0 if self.category_id else 0.0
        
        if interest_rate == 0:
            return 0.0
        
        # Calcular interés según lógica de Testarossa
        if term_difference > 0:
            # Plazo aumentó: interés adicional solo sobre el incremento de plazo
            new_interest = new_capital * interest_rate * term_difference
        else:
            # Plazo igual o menor: recalcular interés total sobre nuevo plazo
            new_interest = new_capital * interest_rate * new_term
        
        return new_interest
    
    def _calc_new_installment_value(self, new_term, capital_down_payment=0.0):
        """
        Calcula el nuevo valor de cuota y todos los componentes financieros
        
        Args:
            new_term: Nuevo número de cuotas
            capital_down_payment: Monto de abono a capital
            
        Returns:
            dict: {
                'new_capital': Capital después del abono,
                'penalty': Penalización aplicada,
                'new_interest': Intereses generados,
                'total_to_finance': Total a financiar (cap + pen + int),
                'installment_value': Valor de cada cuota
            }
        """
        self.ensure_one()
        
        if new_term <= 0:
            return {
                'new_capital': 0,
                'penalty': 0,
                'new_interest': 0,
                'total_to_finance': 0,
                'installment_value': 0,
            }
        
        # Calcular componentes
        new_capital = self.credit_Adeudado - capital_down_payment
        penalty = self._calc_refinance_penalty()
        new_interest = self._calc_new_interest(new_term, capital_down_payment)
        
        # Total a financiar
        total_to_finance = new_capital + penalty + new_interest
        
        # Valor de cuota (simple división, puede personalizarse después)
        installment_value = total_to_finance / new_term if new_term > 0 else 0.0
        
        return {
            'new_capital': new_capital,
            'penalty': penalty,
            'new_interest': new_interest,
            'total_to_finance': total_to_finance,
            'installment_value': installment_value,
        }

    # ============================================
    # REFINANCING CORE METHODS
    # ============================================

    def refinance(self):
        """
        Prepara el crédito para refinanciamiento
        MEJORADO: Ahora incluye validaciones exhaustivas basadas en Testarossa
        H-C02: Toda la operación se ejecuta dentro de un savepoint a nivel
        de cursor. Las líneas con pagos aplicados (amount_paid_total > 0)
        NO se eliminan: se marcan como ``active=False`` para preservar el
        historial de pagos (trazabilidad de auditoría). Solo se hace
        ``unlink`` de las líneas que NO tienen pagos.
        H-C02-bis: El snapshot de ``existing_payments`` se captura ANTES
        del soft-delete para no perder la información si el cursor
        falla a mitad de camino.
        """
        self.ensure_one()

        with self.env.cr.savepoint():
            # ============================================
            # VALIDACIONES CRÍTICAS (Testarossa-style)
            # ============================================

            # 1. Validar estado del crédito
            if self.state != 'approved':
                raise UserError(_(
                    "Solo se pueden refinanciar créditos aprobados.\n"
                    "Estado actual: %s"
                ) % dict(self._fields['state'].selection).get(self.state))

            # 2. Validar saldo pendiente
            self._validate_refinance_balance()

            # 3. Validar que no haya RCVs pendientes
            self._validate_no_pending_rcvs()

            # 4. Validar saldos vencidos según configuración
            self._validate_overdue_balance()

            # ============================================
            # PROCESO DE REFINANCIAMIENTO
            # ============================================

            # H-C02-bis: capturar snapshot de existing_payments ANTES del
            # soft-delete. Si algo revienta entre el write({'active':
            # False}) y el final del savepoint, rollback y no se pierde
            # nada.
            new_existing_payments = []
            for line in self.credit_lines.filtered(lambda l: l.amount_paid_total > 0):
                new_existing_payments.append((0, 0, {
                    'count': line.count,
                    'amount_paid': line.amount_paid_total,
                    'remanente': line.amount_residual,
                    'credit_line_id': line.id,
                    'sale_credit_payment_ids': [(6, 0, line.sale_credit_payment_ids.ids)]
                }))

            # Ahora sí, soft-delete de existing_payments
            if self.existing_payments:
                self.existing_payments.write({'active': False})

            # Poner el crédito en borrador y asociar snapshot
            self.write({
                'state': 'draft',
                'refinance_active': True,
                'existing_payments': new_existing_payments

            })

            # H-C02: NO borrar líneas con pagos. Las líneas pagadas se
            # ocultan (active=False) y se conservan para trazabilidad.
            # Solo las impagas se eliminan.
            paid_lines = self.credit_lines.filtered(
                lambda l: (l.amount_paid_total or 0.0) > 0
            )
            unpaid_lines = self.credit_lines - paid_lines

            if paid_lines:
                _logger.info(
                    "refinance: preservando %d líneas pagadas (active=False) "
                    "del crédito %s para mantener trazabilidad de pagos",
                    len(paid_lines), self.id,
                )
                paid_lines.write({'active': False})

            if unpaid_lines:
                _logger.info(
                    "refinance: eliminando %d líneas impagas del crédito %s",
                    len(unpaid_lines), self.id,
                )
                unpaid_lines.unlink()

            self.message_post(body=_("Crédito preparado para refinanciamiento. Por favor, ajuste los términos del crédito y luego haga clic en 'APLICAR PAGOS'."))

        return {
            'name': 'Refinanciar Crédito',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'sale.credit',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }

    def apply_existing_payments(self):
        self.ensure_one()
        
        if not self.refinance_active:
            raise UserError(_("Esta función solo está disponible para créditos en proceso de refinanciamiento."))
        
        if not self.existing_payments:
            raise UserError(_("No hay pagos previos para aplicar."))
        
   
        active_existing_payments = self.existing_payments.filtered(lambda p: p.active)
        total_paid = sum(payment.amount_paid for payment in active_existing_payments)
        
        # Ordenar las líneas de crédito por fecha de pago esperada
        sorted_lines = self.credit_lines.sorted(key=lambda r: r.expected_date_payment)
        
        amount_to_apply = total_paid
        for line in sorted_lines:
            if amount_to_apply <= 0:
                break
            
            # Buscar el pago correspondiente a esta línea
            existing_payment = self.existing_payments.filtered(lambda p: p.count == line.count)
            
            if line.amount_fixed <= amount_to_apply:
                # Pagar la línea completa
                line.write({
                    'amount_paid_total': line.amount_fixed,
                    'date_payment': existing_payment.date_payment if existing_payment else fields.Date.today(),
                    'amount_residual': 0,
                    'state': 'paid',
                    'sale_credit_payment_ids': [(6, 0, existing_payment.sale_credit_payment_ids.ids)]

                })
                amount_to_apply -= line.amount_fixed
            else:
                # Pago parcial de la línea
                line.write({
                    'amount_paid_total': amount_to_apply,
                    'date_payment': existing_payment.date_payment if existing_payment else fields.Date.today(),
                    'amount_residual': line.amount_fixed - amount_to_apply,
                    'state': 'pending',
                    'sale_credit_payment_ids': [(6, 0, existing_payment.sale_credit_payment_ids.ids)]

                })
                amount_to_apply = 0
            
            # Actualizar o crear la línea de pago correspondiente
            payment_line = self.env['sale.credit.payment.line'].search([
                ('credit_line_id', '=', line.id),
                ('sale_payment_id.credit_id', '=', self.id)
            ], limit=1)
            
            if payment_line:
                payment_line.write({
                    'amount_paid': line.amount_paid_total,
                    'amount_payable': line.amount_fixed,
                    'remanente': line.amount_residual,
                    'state': line.state
                })
            else:
                self.env['sale.credit.payment.line'].create({
                    'sale_payment_id': self.credit_payments[0].id if self.credit_payments else False,
                    'credit_line_id': line.id,
                    'amount_paid': line.amount_paid_total,
                    'amount_payable': line.amount_fixed,
                    'remanente': line.amount_residual,
                    'state': line.state,
                    'count': line.count,
                    'partner_id': self.partner_id.id,
                })
        
        # Vincular todos los pagos existentes a las líneas que recibieron pagos
        paid_lines = self.credit_lines.filtered(lambda l: l.amount_paid_total > 0)
        all_payment_ids = []
        for payment in self.existing_payments:
            if payment.sale_credit_payment_ids:
                all_payment_ids.extend(payment.sale_credit_payment_ids.ids)
        
        if all_payment_ids:
            paid_lines.write({'sale_credit_payment_ids': [(6, 0, all_payment_ids)]})
        
        # Actualizar el estado del crédito
        self.write({
            'state': 'approved',
            'refinance_active': False
        })
        self.optimization_dinamic()
        
        self.message_post(body=_("Se han aplicado pagos existentes por un total de %s.") % total_paid)
        
        if amount_to_apply > 0:
            self.message_post(body=_("Quedó un saldo sin aplicar de %s") % amount_to_apply)
        
        # Limpiar los pagos existentes almacenados temporalmente
        self.existing_payments.unlink()
        active_existing_payments.write({'active': False})

        return True

    
    def action_update_payment_status(self):
        pass

    def action_view_sale(self):
        action = self.env.ref('sale.action_orders').read()[0]
        action['views'] = [(self.env.ref('sale.view_order_form').id, 'form')]
        action['res_id'] = self.sale_id.id
        return action

    def action_view_picking(self):
        pass

    def action_view_invoices(self):
        pass

    def action_view_massive_credit_payments(self):
        pass

    def action_view_credit_lines(self):
        '''
        This function returns an action that display existing
        '''
        creditlines = self.credit_lines
        action = self.env["ir.actions.actions"]._for_xml_id(
            "cjg_finance.sale_credit_line_action")
        if creditlines:
            if len(creditlines) > 1:
                action['domain'] = [('id', 'in', creditlines.ids)]
            elif creditlines:
                form_view = [
                    (self.env.ref('cjg_finance.sale_credit_line_view_form').id, 'form')]
                if 'views' in action:
                    action['views'] = form_view + \
                        [(state, view)
                         for state, view in action['views'] if view != 'form']
                else:
                    action['views'] = form_view
                action['res_id'] = creditlines.id
            action['context'] = dict(
                self._context, default_partner_id=self.partner_id.id, default_credit_id=self.id)
            return action

    def print_credit_report(self):
        self.ensure_one()
        return self.env.ref('cjg_finance.action_report_sale_credit').report_action(self)

    def action_view_credit_overdues(self):
        pass

    # def action_view_credit_payments(self):
    #     return {
    #         'name': 'Payments',
    #         'view_type': 'tree',
    #         'view_mode': 'tree',
    #         'view_id': self.env.ref('account.view_account_payment_tree').id,
    #         'res_model': 'account.payment',
    #         'domain': [('sale_credit_id', '=', self.id)],
    #         'type': 'ir.actions.act_window',
    #         'target': 'current',
    #     }

    # def payment_register(self):
    #     self.account_payment_ids
    #     sale_credit_payment = self.env['sale.credit.payment'].search(
    #         [('credit_id', '=', self.id)])
    #     for sale_pay in sale_credit_payment:
    #         print(sale_pay.name)
    #         print(sale_pay.amount_total)
    #         print(sale_pay.payment_id.id)
    #
    #     payment_line = sale_credit_payment.credit_payment_lines.search(
    #         [('amount_paid', '!=', 0)])
    #     for count in payment_line:
    #         print(count.count)
    #         print(count.credit_line_id.name)
    #         print(count.state)

    def action_open_website(self):
        pass

    # ========== CONSTRAINTS DE INTEGRIDAD ==========

    @api.ondelete(at_uninstall=False)
    def _unlink_check_process_status(self):
        for record in self:
            if record.process_detail_status != 'normal':
                raise UserError(_(
                    'No se puede eliminar el contrato %s porque tiene un proceso especial activo (%s). '
                    'Archive el contrato en su lugar.'
                ) % (record.name, record.process_detail_status))

    @api.constrains('capitalized_amount', 'origin_credit_id')
    def _check_capitalized_amount(self):
        for record in self:
            if record.capitalized_amount and record.origin_credit_id:
                max_capital = record.origin_credit_id.process_capital_paid
                if record.capitalized_amount > max_capital + 0.01:
                    raise ValidationError(_(
                        'El monto capitalizado (%s) no puede superar el capital pagado '
                        'del contrato origen (%s).'
                    ) % (record.capitalized_amount, max_capital))

    # ========== CRON JOBS DE ANULACIÓN Y DESISTIMIENTO AUTOMÁTICO ==========

    @api.model
    def _cron_auto_cancel_contracts(self):
        """
        Ejecutar al final de cada mes.
        Cancela contratos en estado 'approved' sin ninguna cuota pagada
        cuya fecha de inicio sea del mes anterior.
        """
        today = fields.Date.today()
        # Solo ejecutar el último día del mes
        next_day = today + timedelta(days=1)
        if next_day.month == today.month:
            return  # No es el último día del mes

        first_of_last_month = today.replace(day=1) - relativedelta(months=1)
        last_of_last_month = today.replace(day=1) - timedelta(days=1)

        candidates = self.search([
            ('state', '=', 'approved'),
            ('date_start', '>=', first_of_last_month),
            ('date_start', '<=', last_of_last_month),
            ('active', '=', True),
        ])

        cancelled = 0
        errors = 0
        for credit in candidates:
            try:
                paid_lines = credit.credit_lines.filtered(lambda l: l.state == 'paid')
                if not paid_lines:
                    credit.write({
                        'state': 'cancelled',
                        'process_detail_status': 'normal',
                    })
                    credit.credit_lines.filtered(
                        lambda l: l.state in ('pending', 'paid_overdue')
                    ).write({'state': 'cancelled'})
                    credit.message_post(
                        body=_('Contrato anulado automáticamente por falta de primer pago. '
                               'Ejecutado por: Cron_Anulacion %s') % fields.Datetime.now()
                    )
                    cancelled += 1
            except Exception as e:
                _logger.error('Cron_Anulacion: error en contrato %s: %s', credit.name, str(e))
                errors += 1

        _logger.info('Cron_Anulacion: evaluados=%d, cancelados=%d, errores=%d',
                     len(candidates), cancelled, errors)

    @api.model
    def _cron_auto_withdraw_contracts(self):
        """
        Ejecutar diariamente.
        - Contratos con 3+ cuotas vencidas → estado 'withdrawing'
        - Contratos en 'withdrawing' al fin de mes sin pagos → estado 'withdrawn'
        - Revertir 'withdrawing' si se pagaron todas las cuotas vencidas
        """
        today = fields.Date.today()

        # Paso 1: Identificar contratos con 3+ cuotas vencidas → withdrawing
        approved_contracts = self.search([
            ('state', '=', 'approved'),
            ('active', '=', True),
        ])
        for credit in approved_contracts:
            try:
                overdue_lines = credit.credit_lines.filtered(
                    lambda l: l.state in ('paid_overdue', 'pending')
                              and l.expected_date_payment
                              and l.expected_date_payment < today
                )
                if len(overdue_lines) >= 3:
                    credit.write({'state': 'withdrawing'})
                    credit.message_post(
                        body=_('Contrato marcado "Por Desistir" por %d cuotas vencidas. '
                               'Cron_Desistimiento %s') % (len(overdue_lines), today)
                    )
            except Exception as e:
                _logger.error('Cron_Desistimiento paso1: error en contrato %s: %s', credit.name, str(e))

        # Paso 2: Al fin de mes, contratos en 'withdrawing' sin pagos en el mes → withdrawn
        next_day = today + timedelta(days=1)
        if next_day.month != today.month:  # Es el último día del mes
            withdrawing = self.search([
                ('state', '=', 'withdrawing'),
                ('active', '=', True),
            ])
            for credit in withdrawing:
                try:
                    payments_this_month = credit.credit_payments.filtered(
                        lambda p: p.payment_date and p.payment_date.month == today.month
                                  and p.payment_date.year == today.year
                    )
                    if not payments_this_month:
                        credit.write({'state': 'withdrawn'})
                        credit.message_post(
                            body=_('Contrato desistido automáticamente al cierre del mes. '
                                   'Sin pagos en %s/%s. Cron_Desistimiento') % (today.month, today.year)
                        )
                except Exception as e:
                    _logger.error('Cron_Desistimiento paso2: error en contrato %s: %s', credit.name, str(e))

        # Paso 3: Revertir 'withdrawing' si se pagaron todas las cuotas vencidas
        still_withdrawing = self.search([
            ('state', '=', 'withdrawing'),
            ('active', '=', True),
        ])
        for credit in still_withdrawing:
            try:
                overdue_lines = credit.credit_lines.filtered(
                    lambda l: l.state in ('paid_overdue', 'pending')
                              and l.expected_date_payment
                              and l.expected_date_payment < today
                )
                if not overdue_lines:
                    credit.write({'state': 'approved'})
                    credit.message_post(
                        body=_('Contrato revertido a Aprobado: todas las cuotas vencidas fueron pagadas.')
                    )
            except Exception as e:
                _logger.error('Cron_Desistimiento paso3: error en contrato %s: %s', credit.name, str(e))

    def action_open_devolucion_wizard(self):
        """Open the devolucion wizard for this contract."""
        self.ensure_one()
        if self.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para devolución. '
                'Solo contratos en estado Anulado o Desistido pueden solicitar devolución.'
            ) % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Devolución de Contrato'),
            'res_model': 'sale.credit.devolucion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_open_mejora_wizard(self):
        """Open the mejora wizard for this contract."""
        self.ensure_one()
        if self.state not in ('approved', 'closed'):
            raise UserError(_(
                'El contrato %s no es elegible para mejora. '
                'Solo contratos en estado Aprobado o Saldado pueden mejorar.'
            ) % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mejora de Producto'),
            'res_model': 'sale.credit.mejora.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id},
        }

    def action_register_no_refund(self):
        """
        Register that the client opts for no refund (Opción 2).
        Validates state, sets no_refund fields, and posts to chatter.
        """
        self.ensure_one()
        if self.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para registrar la opción de no reembolso. '
                'Solo contratos en estado Anulado o Desistido pueden usar esta opción.'
            ) % self.name)
        if self.no_refund_registered:
            raise UserError(_(
                'El contrato %s ya tiene registrada la opción de no reembolso.'
            ) % self.name)

        self.write({
            'no_refund_registered': True,
            'no_refund_date': fields.Date.today(),
            'no_refund_user_id': self.env.user.id,
        })

        self.message_post(
            body=_(
                'Opción 2 (Sin Reembolso) registrada.<br/>'
                'El cliente ha decidido no solicitar reembolso del capital pagado.<br/>'
                'Registrado por: %s<br/>'
                'Fecha: %s'
            ) % (self.env.user.name, fields.Date.today())
        )
        return True

    # ========== TRACK 3 (F10) — STATUS AUTO-CHANGE ON AGING ==========
    # Replica testarossa/php_script/script_cambio_estatus_contratos.php
    #
    # Reglas:
    #   - Cuota vencida > 30 días → 'withdrawing' (por desistir)
    #   - Cuota vencida > 60 días → 'withdrawn'  (desistido)
    #   - Cuota vencida > 90 días → 'legal'      (en legal)
    # Cada cambio se audita en chatter (mail.message) y en el modelo
    # cjg.finance.status.aging.audit (1 fila por cambio).

    @api.model
    def _cron_change_status_aging(self):
        """
        Cron diario: cambia el estado de los contratos según el aging
        de sus cuotas (paridad con
        testarossa/php_script/script_cambio_estatus_contratos.php).

        IMPORTANTE (sprint 23, GAP-12.03):
            Usa el servicio central de transiciones FSM
            (``sale.credit.transition.service``) en lugar de ``write()``
            directo. Esto evita que la validación FSM del ``write()``
            (sprint 22) rechace las transiciones.
        """
        today = fields.Date.today()
        Audit = self.env['cjg.finance.status.aging.audit']
        transition_service = self.env['sale.credit.transition.service']

        # Buscar contratos activos con al menos una cuota vencida
        candidates = self.search([
            ('state', 'in', ['approved', 'active', 'withdrawing']),
            ('active', '=', True),
        ])

        stats = {
            'to_withdrawing': 0,
            'to_withdrawn': 0,
            'to_legal': 0,
            'revert_approved': 0,
            'errors': 0,
        }

        for credit in candidates:
            try:
                # Calcular días de atraso máximo del contrato
                overdue_lines = credit.credit_lines.filtered(
                    lambda l: l.state in ('paid_overdue', 'pending')
                              and l.expected_date_payment
                              and l.expected_date_payment < today
                )
                if not overdue_lines:
                    # Si tiene 'withdrawing' pero ya no tiene cuotas
                    # vencidas, revertir a 'approved'.
                    if credit.state == 'withdrawing':
                        old_state = credit.state
                        # GAP-12.03: usar servicio FSM (no write directo)
                        result = transition_service.transition_with_path(
                            credit, 'approved',
                            reason=_('Cron Status Aging: sin cuotas vencidas'),
                        )
                        if not result['success']:
                            _logger.warning(
                                'Cron_StatusAging: no se pudo revertir %s: %s',
                                credit.display_name, result.get('reason'),
                            )
                        Audit.create({
                            'credit_id': credit.id,
                            'from_state': old_state,
                            'to_state': 'approved',
                            'rule': 'revert_paid',
                            'days_overdue': 0,
                            'affected_lines': 0,
                            'note': _('Todas las cuotas vencidas fueron pagadas.'),
                        })
                        credit.message_post(
                            body=_('Contrato revertido a Aprobado '
                                   '(Aging: sin cuotas vencidas). '
                                   'Ejecutado por Cron_StatusAging %s') % fields.Datetime.now()
                        )
                        stats['revert_approved'] += 1
                    continue

                days_overdue = max(
                    (today - l.expected_date_payment).days
                    for l in overdue_lines
                )
                num_overdue = len(overdue_lines)
                new_state = None
                rule = None
                if days_overdue > 90 and credit.state != 'legal':
                    new_state = 'legal'
                    rule = 'overdue_90'
                elif days_overdue > 60 and credit.state != 'withdrawn':
                    new_state = 'withdrawn'
                    rule = 'overdue_60'
                elif days_overdue > 30 and credit.state != 'withdrawing':
                    new_state = 'withdrawing'
                    rule = 'overdue_30'

                if new_state and new_state != credit.state:
                    old_state = credit.state
                    # GAP-12.03: usar servicio FSM (no write directo)
                    result = transition_service.transition_with_path(
                        credit, new_state,
                        reason=_('Cron Status Aging: regla %s, %d días de atraso') % (rule, days_overdue),
                    )
                    if not result['success']:
                        _logger.warning(
                            'Cron_StatusAging: no se pudo transicionar %s a %s: %s',
                            credit.display_name, new_state, result.get('reason'),
                        )
                        stats['errors'] += 1
                        continue
                    Audit.create({
                        'credit_id': credit.id,
                        'from_state': old_state,
                        'to_state': new_state,
                        'rule': rule,
                        'days_overdue': days_overdue,
                        'affected_lines': num_overdue,
                        'note': _(
                            'Cambio automático de status por aging. '
                            '%(days)d días de atraso, %(lines)d cuota(s) vencida(s).'
                        ) % {'days': days_overdue, 'lines': num_overdue},
                    })
                    credit.message_post(
                        body=_(
                            '<b>Cron Status Aging:</b> %(old)s → <b>%(new)s</b> '
                            '<br/>Regla: %(rule)s<br/>'
                            'Días de atraso: %(days)d<br/>'
                            'Cuotas vencidas: %(lines)d<br/>'
                            'Ejecutado: %(when)s'
                        ) % {
                            'old': old_state,
                            'new': new_state,
                            'rule': rule,
                            'days': days_overdue,
                            'lines': num_overdue,
                            'when': fields.Datetime.now(),
                        },
                        subject=_('Cambio de status por aging'),
                    )
                    if rule == 'overdue_30':
                        stats['to_withdrawing'] += 1
                    elif rule == 'overdue_60':
                        stats['to_withdrawn'] += 1
                    elif rule == 'overdue_90':
                        stats['to_legal'] += 1

            except Exception as e:
                _logger.error(
                    'Cron_StatusAging: error en contrato %s: %s',
                    credit.name, str(e),
                )
                stats['errors'] += 1

        _logger.info(
            'Cron_StatusAging: evaluados=%d, withdrawing=%d, withdrawn=%d, '
            'legal=%d, revert=%d, errores=%d',
            len(candidates),
            stats['to_withdrawing'],
            stats['to_withdrawn'],
            stats['to_legal'],
            stats['revert_approved'],
            stats['errors'],
        )
        return stats
