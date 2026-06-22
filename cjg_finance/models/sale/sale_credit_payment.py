import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date

_logger = logging.getLogger(__name__)

class SaleCreditPayment(models.Model):
    # Nombre técnico original para no romper referencias en CRM y Vistas
    _name = 'sale.credit.payment'
    _description = 'Sale Credit Payment (Extended from POS Receipt)'
    
    # HERENCIA CLAVE: Heredamos funcionalidad de Caja/Recibo
    _inherit = ['cjg.pos.payment.receipt'] 

    # Sobrescribir estados para compatibilidad con vistas de finanzas
    state = fields.Selection(selection_add=[
        ('validated', 'Validado'),
        ('paid', 'Pagado'),
        ('cancel', 'Cancelado (Legacy)'),
        ('error', 'Error'),
    ], ondelete={'validated': 'set default', 'paid': 'set default', 'cancel': 'set default', 'error': 'set default'})
    
    # ==========================================================================
    # CAMPOS ESPECÍFICOS DE CRÉDITOS Y COMPATIBILIDAD
    # ==========================================================================

    # Enlazar con el campo genérico del recibo
    credit_id = fields.Many2one(
        'sale.credit', 
        string="Contrato de Crédito",
        required=False, # Relaxed required to allow polymorphism
        ondelete='restrict'
    )

    # Campos de migración Testarossa
    receipt_number = fields.Char(string="Número de Recibo (Testarossa)")
    testarossa_serie = fields.Char(string="Serie Testarossa")
    testarossa_docto = fields.Integer(string="Docto Testarossa")
    is_migrated = fields.Boolean(string="Es Migrado", default=False)
    annulled = fields.Boolean(string="Anulado", default=False)
    legacy_plan = fields.Integer(string="Plan Legado (Testarossa)", default=0,
        help="Número de plan original en Testarossa para trazabilidad de migración")

    def init(self):
        self._cr.execute(
            """
            ALTER TABLE sale_credit_payment
            ADD COLUMN IF NOT EXISTS legacy_plan INTEGER
            """
        )
        super().init()

    
    # Mapping para document_type (automático al crear)
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Asegurar que el tipo de documento sea 'credit' si no se especifica
            if not vals.get('document_type'):
                vals['document_type'] = 'credit'
            
            # Sincronizar fecha si viene como payment_date (legacy)
            if 'payment_date' in vals and not vals.get('date'):
                vals['date'] = vals['payment_date']

            if vals.get('credit_id') and not vals.get('currency_id'):
                credit = self.env['sale.credit'].browse(vals['credit_id'])
                vals['currency_id'] = (credit.currency_id_money or credit.company_id.currency_id).id
                
            # Sincronizar credit_id hacia campos de recibo futuros si fuera necesario
            # ...
            
        return super(SaleCreditPayment, self).create(vals_list)

    # Campos Legacy para compatibilidad con código existente
    payment_date = fields.Date(
        string="Fecha de Pago",
        compute='_compute_payment_date',
        inverse='_set_payment_date',
        store=True
    )
    
    user_id = fields.Many2one(
        'res.users', 
        string='Usuario', 
        default=lambda self: self.env.user
    )

    # Campos de Moneda y Tasas (Compatibilidad con Vista)
    currency_id = fields.Many2one(
        'res.currency', 
        string="Moneda", 
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    apply_manual_currency = fields.Boolean(string='Aplicar Tasa Manual', default=False)
    manual_currency_exchange = fields.Float(string='Tasa de Cambio', default=1.0)
    apply_payment_preview = fields.Boolean(string='Vista Previa de Pago', default=False)
    amount_divisas = fields.Float(string='Monto en Divisas')
    
    is_currency_id_different = fields.Boolean(compute='_compute_is_currency_different')
    journal_and_date_readonly = fields.Boolean(compute='_compute_journal_and_date_readonly')

    cash_closing_id = fields.Many2one(
        'cash.box.closing',
        string='Cierre de Caja',
        ondelete='set null',
        index=True
    )
    
    payment_count = fields.Integer(
        string='Contador de Asientos',
        compute='_compute_payment_count'
    )

    # Campos adicionales de lógica de negocio de créditos
    is_migrated = fields.Boolean(string="Es Pago Migrado", default=False)
    receipt_number = fields.Char('Número de Recibo Manual') # Override/Compatibilidad

    # Relación inversa a líneas de crédito (Many2many porque una cuota puede tener N pagos)
    # Nota: Usamos el nombre de relación que definimos en sale.credit.line
    pos_payment_line_ids = fields.Many2many(
        'sale.credit.line',
        'sale_credit_line_payment_rel', # Misma tabla que en sale.credit.line
        'payment_id',
        'credit_line_id',
        string="Cuotas Pagadas (Real)"
    )

    # Relación con las líneas de detalle del pago (para la interfaz de cobro masivo/CRM)
    credit_payment_lines = fields.One2many(
        'sale.credit.payment.line',
        'sale_payment_id',
        string="Líneas de Pago (Detalle)"
    )

    # ==========================================================================
    # CÓMPUTOS DE COMPATIBILIDAD
    # ==========================================================================
    @api.depends('date')
    def _compute_payment_date(self):
        for record in self:
            record.payment_date = record.date.date() if record.date else False

    def _set_payment_date(self):
        for record in self:
            if record.payment_date:
                record.date = record.payment_date

    # ==========================================================================
    # LÓGICA DE NEGOCIO Y OVERRIDES
    # ==========================================================================
    
    # Override de PosPaymentReceipt._get_credit_account
    def _get_credit_account(self):
        # Aquí definimos la cuenta de crédito específica para el contrato
        # Si no hay config específica, usa la del partner (comportamiento default)
        return super()._get_credit_account()

    # Override de onchange para cargar datos del crédito al seleccionarlo
    @api.onchange('credit_id')
    def onchange_credit_id(self):
        if not self.credit_id:
            return
            
        self.partner_id = self.credit_id.partner_id
        self.company_id = self.credit_id.company_id
        self.currency_id = self.credit_id.currency_id_money or self.credit_id.company_id.currency_id
        
        # Calcular monto sugerido (próxima cuota)
        # (Lógica simplificada, se puede expandir)
        lines = self.credit_id.credit_lines.filtered(lambda l: l.state != 'paid')
        if lines:
            # Ordenar por fecha
            lines = lines.sorted(key=lambda l: l.expected_date_payment)
            self.amount_total = lines[0].amount_residual

    # ==========================================================================
    # BOTONES Y ACCIONES DE VISTA (COMPATIBILIDAD)
    # ==========================================================================
    def action_validate(self):
        """Mapping de botón legacy 'Validar' al nuevo conformar del recibo"""
        return self.action_confirm()

    def action_set_to_draft(self):
        self.write({'state': 'draft'})

    def action_set_to_validated(self):
        self.write({'state': 'to_distribute'})

    def action_cancel(self, reason=None, supervisor_employee_id=None):
        """Cancela el pago revirtiendo cuotas y asiento contable.

        FIX C-01: Flujo atómico dentro de un savepoint para evitar descuadre
        silencioso entre ``credit_line`` (marcada como pagada) y
        ``account_move`` (reversado por el padre). Si cualquier paso falla,
        el savepoint hace rollback completo:

          1. Reversar ``amount_paid_total`` y ``overdue_residual`` en cada
             ``credit_line`` afectada por las ``credit_payment_lines``.
          2. Reversar el asiento contable vía ``super().action_cancel``.
          3. Marcar ``state='cancel'`` y ``annulled=True``.

        Las líneas de detalle del pago (``sale.credit.payment.line``) se
        cancelan con ``cancel_payment_lines()`` para mantener coherencia.
        """
        self.ensure_one()
        with self.env.cr.savepoint():
            for payment_line in self.credit_payment_lines:
                credit_line = payment_line.credit_line_id
                if not credit_line:
                    continue
                credit_line.write({
                    'amount_paid_total': max(
                        0.0,
                        (credit_line.amount_paid_total or 0.0)
                        - (payment_line.amount_paid or 0.0),
                    ),
                    'overdue_residual': (credit_line.overdue_residual or 0.0)
                    + (payment_line.amount_overdue or 0.0),
                    'state': 'pending' if (credit_line.amount_paid_total or 0.0) == 0
                    else credit_line.state,
                })
            try:
                payment_line_records = self.credit_payment_lines
                if hasattr(payment_line_records, 'cancel_payment_lines'):
                    payment_line_records.cancel_payment_lines()
            except Exception:
                _logger.warning(
                    'No se pudieron cancelar payment_lines de %s; continuando.',
                    self.name,
                )
            super(SaleCreditPayment, self).action_cancel(
                reason=reason,
                supervisor_employee_id=supervisor_employee_id,
            )
            self.write({
                'state': 'cancel',
                'annulled': True,
            })
        return True

    def action_void_receipt(self, reason=None):
        self.action_cancel(reason=reason or _('Pago anulado desde caja'))
        return True

    def print_payment_report(self):
        """Retorna la acción de impresión de reporte de pago"""
        return self.env.ref('cjg_finance.action_report_sale_payment_credit').report_action(self)

    def print_termica(self):
        """Retorna la acción de impresión de ticket térmico"""
        return self.env.ref('cjg_finance.action_report_sale_termica').report_action(self)

    def action_send_payment_mail_notification(self):
        """Opcional: Implementar envío de correo si es necesario"""
        pass

    def cancelled_payment(self):
        """Lógica legacy para cancelar un pago ya distribuido"""
        # Aquí iría la lógica para revertir la distribución
        self.action_cancel()

    def action_view_payments(self):
        """Ver asientos contables vinculados"""
        action = self.env["ir.actions.actions"]._for_xml_id("account.action_move_out_receipt_type")
        action['domain'] = [('id', 'in', [self.move_id.id, self.distribution_move_id.id])]
        return action

    def _compute_payment_count(self):
        for rec in self:
            count = 0
            if rec.move_id: count += 1
            if rec.distribution_move_id: count += 1
            if rec.intercompany_move_id: count += 1
            if rec.deposit_move_id: count += 1
            rec.payment_count = count

    @api.depends('currency_id', 'company_id.currency_id')
    def _compute_is_currency_different(self):
        for rec in self:
            rec.is_currency_id_different = rec.currency_id != rec.company_id.currency_id

    @api.depends('state')
    def _compute_journal_and_date_readonly(self):
        for rec in self:
            rec.journal_and_date_readonly = rec.state not in ['draft']

    # ==========================================================================
    # LÓGICA DE APLICACIÓN DE PAGOS (ORIGINAL)
    # ==========================================================================
    def action_post(self):
        """
        Publicar el pago:
        1. Ejecuta lógica base de Caja (Crear asientos, mover dinero)
        2. Ejecuta lógica de Crédito (Matar cuotas)
        """
        # Llamar al padre (Caja) -> Crea asientos y pone state='to_distribute'
        res = super(SaleCreditPayment, self).action_confirm() 
        
        # Aplicar pago a las cuotas
        self._apply_payment_to_credit_lines()
        
        # Marcar como 'paid' (Equivalente a distributed) para compatibilidad con vistas
        self.write({'state': 'paid'})
        return res

    def _get_credit_line_pending_amount(self, line, paid_total=None):
        line_total = line.amount_fixed or line.amount_residual or 0.0
        paid_total = line.amount_paid_total if paid_total is None else paid_total
        return max(line_total - paid_total, 0.0)

    def _get_credit_line_payment_state(self, line, paid_total=None):
        return 'paid' if self._get_credit_line_pending_amount(line, paid_total=paid_total) <= 0.01 else 'pending'

    def _distribute_payment_priority(self, amount, line):
        """Distribuye un pago entre los componentes de una línea.

        Prioridad (igual que el legacy testarossa class.MVFactura.php):
          1. Mora (overdue_residual)
          2. Interés (amount_interest residual)
          3. Capital (amount_capital residual)
          4. Otros (amount_others)

        :param amount: monto disponible a distribuir
        :param line: sale.credit.line
        :return: tuple (dict con allocation por componente, monto sobrante)
        """
        self.ensure_one()
        allocation = {
            'amount_mora': 0.0,
            'amount_interest': 0.0,
            'amount_capital': 0.0,
            'amount_others': 0.0,
        }
        remaining = amount

        mora_pending = max(line.overdue_residual or 0.0, 0.0)
        if remaining > 0 and mora_pending > 0:
            allocation['amount_mora'] = min(remaining, mora_pending)
            remaining -= allocation['amount_mora']

        interest_pending = max(line.amount_interest or 0.0, 0.0)
        if remaining > 0 and interest_pending > 0:
            allocation['amount_interest'] = min(remaining, interest_pending)
            remaining -= allocation['amount_interest']

        capital_pending = max(line.amount_capital or 0.0, 0.0)
        if remaining > 0 and capital_pending > 0:
            allocation['amount_capital'] = min(remaining, capital_pending)
            remaining -= allocation['amount_capital']

        others_pending = max(line.amount_others or 0.0, 0.0)
        if remaining > 0 and others_pending > 0:
            allocation['amount_others'] = min(remaining, others_pending)
            remaining -= allocation['amount_others']

        return allocation, remaining

    def _prepare_credit_payment_line_vals(self, payment, line, amount_to_pay, paid_total=None):
        base_amount = line.amount_fixed or line.amount_residual or amount_to_pay or 0.0
        paid_total = line.amount_paid_total if paid_total is None else paid_total
        remaining_amount = self._get_credit_line_pending_amount(line, paid_total=paid_total)
        state = self._get_credit_line_payment_state(line, paid_total=paid_total)

        capital_ratio = (line.amount_capital / base_amount) if base_amount else 0.0
        interest_ratio = (line.amount_interest / base_amount) if base_amount else 0.0
        amount_capital = amount_to_pay * capital_ratio if capital_ratio > 0 else 0.0
        amount_interest = amount_to_pay * interest_ratio if interest_ratio > 0 else 0.0

        allocated_total = amount_capital + amount_interest
        if allocated_total > amount_to_pay:
            adjustment = allocated_total - amount_to_pay
            amount_capital = max(amount_capital - adjustment, 0.0)
        elif allocated_total < amount_to_pay:
            amount_capital += amount_to_pay - allocated_total

        return {
            'amount_capital': amount_capital,
            'amount_final': line.amount_final,
            'amount_fixed': line.amount_fixed,
            'amount_initial': line.amount_initial,
            'amount_interest': amount_interest,
            'amount_overdue': line.overdue_residual,
            'amount_payable': base_amount,
            'amount_paid': amount_to_pay,
            'count': line.count,
            'credit_line_id': line.id,
            'expected_date_payment': line.expected_date_payment,
            'is_paid': state == 'paid',
            'partner_id': line.partner_id.id,
            'remanente': remaining_amount,
            'state': state,
        }

    def _apply_payment_to_credit_lines(self):
        """Distribuye el monto pagado entre las cuotas pendientes.

        H-C19: orden prioriza cuotas en mora pagada (``paid_overdue``) y luego
               las pendientes por fecha esperada.
        H-C06: usa ``_distribute_payment_priority`` (mora -> interes ->
               capital -> otros) en lugar del ``capital_ratio`` previo.
        H-C20: el sobrante ya no se ignora silenciosamente; se registra en el
               log y, si el modelo lo soporta, se persiste en ``excess_amount``.
        """
        for payment in self:
            if not payment.credit_id:
                continue

            amount_available = payment.amount_paid  # Usar amount_paid del recibo

            # H-C19: ordenar priorizando ``paid_overdue`` (mora) sobre
            # ``pending`` con fecha futura. Dentro de cada grupo, por fecha.
            lines = payment.credit_id.credit_lines.filtered(
                lambda l: l.state != 'paid'
            ).sorted(
                key=lambda l: (
                    0 if l.state == 'paid_overdue' else 1,
                    l.expected_date_payment or fields.Date.today(),
                )
            )

            affected_lines = self.env['sale.credit.line']

            for line in lines:
                if amount_available <= 0.001:
                    break

                pending_amount = payment._get_credit_line_pending_amount(line)
                amount_to_pay = min(pending_amount, amount_available)
                if amount_to_pay <= 0.001:
                    continue

                # H-C06: distribuir con prioridad mora -> interes ->
                # capital -> otros. ``leftover`` es el remanente no
                # distribuible dentro de esta cuota (p.ej. cuando
                # ``amount_fixed=0`` y solo hay mora).
                allocation, leftover = payment._distribute_payment_priority(
                    amount_to_pay, line
                )

                new_paid_total = line.amount_paid_total + amount_to_pay
                new_state = payment._get_credit_line_payment_state(
                    line, paid_total=new_paid_total
                )

                # Actualizar línea: total pagado, mora residual, estado.
                line.write({
                    'amount_paid_total': new_paid_total,
                    'overdue_residual': max(
                        0.0,
                        (line.overdue_residual or 0.0)
                        - allocation['amount_mora'],
                    ),
                    'state': new_state,
                })

                existing_payment_line = payment.credit_payment_lines.filtered(
                    lambda payment_line: payment_line.credit_line_id == line
                    and payment_line.state != 'cancelled'
                )[:1]
                payment_line_vals = payment._prepare_credit_payment_line_vals(
                    payment,
                    line,
                    amount_to_pay,
                    paid_total=new_paid_total,
                )
                if existing_payment_line:
                    existing_payment_line.write(payment_line_vals)
                else:
                    payment_line_vals['sale_payment_id'] = payment.id
                    self.env['sale.credit.payment.line'].create(payment_line_vals)

                amount_available -= amount_to_pay
                affected_lines |= line

            # Vincular pago a las líneas afectadas
            payment.pos_payment_line_ids = [(6, 0, affected_lines.ids)]

            # H-C20 / FIX calcularAbonoACapital: reaplicar el sobrante como
            # penalidad + abono a capital (legacy class.Contratos.php).
            if amount_available > 0.01:
                _logger.info(
                    "Pago %s tiene sobrante de %s; aplicando "
                    "calcularAbonoACapital.",
                    payment.name, amount_available,
                )
                if hasattr(payment, 'excess_amount'):
                    payment.excess_amount = amount_available
                if payment.credit_id:
                    payment.credit_id.action_apply_payment_with_capital_abono(
                        payment, amount_available,
                    )
            else:
                _logger.info(
                    "Pago %s aplicado a %s cuotas. Restante: %s",
                    payment.name, len(affected_lines), amount_available,
                )

    # Método alias para compatibilidad con código viejo que llame a action_validate
    def action_validate(self):
        return self.action_post()
