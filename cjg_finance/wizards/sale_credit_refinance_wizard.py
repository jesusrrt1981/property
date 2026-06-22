
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class CreditRefinanceWizard(models.TransientModel):
    _name = 'sale.credit.refinance.wizard'
    _description = 'Wizard Mejorado para Refinanciamiento de Crédito'

    # ============================================
    # RELACIÓN
    # ============================================
    
    credit_id = fields.Many2one(
        'sale.credit', 
        string='Crédito', 
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get('active_id')
    )
    
    # ============================================
    # DATOS ACTUALES (solo lectura)
    # ============================================
    
    current_balance = fields.Float(
        string='Saldo Actual',
        related='credit_id.amount_residual',
        readonly=True
    )
    current_installments_pending = fields.Integer(
        string='Cuotas Pendientes',
        compute='_compute_current_data',
        readonly=True
    )
    current_installment_value = fields.Monetary(
        string='Valor Cuota Actual',
        compute='_compute_current_data',
        currency_field='currency_id',
        readonly=True
    )
    current_interest_rate = fields.Float(
        string='Tasa Actual (%)',
        related='credit_id.category_id.percent_interest',
        readonly=True
    )
    
    # ============================================
    # PARÁMETROS DEL REFINANCIAMIENTO (inputs)
    # ============================================
    
    capital_down_payment = fields.Monetary(
        string='Abono a Capital',
        currency_field='currency_id',
        required=True,
        default=0.0,
        help="Monto que el cliente abona al capital al momento de refinanciar"
    )
    new_term = fields.Integer(
        string='Nuevo Plazo (meses)',
        required=True,
        default=lambda self: self._default_new_term(),
        help="Número de cuotas del nuevo plan de pagos"
    )
    new_category_id = fields.Many2one(
        'sale.credit.category',
        string='Nueva Categoría/Tasa',
        help="Dejar vacío para mantener la tasa actual"
    )
    
    # ============================================
    # CÁLCULOS AUTOMÁTICOS (solo lectura)
    # ============================================
    
    new_capital = fields.Monetary(
        string='Nuevo Capital',
        compute='_compute_new_plan',
        currency_field='currency_id',
        store=False,
        help="Capital después del abono"
    )
    penalty = fields.Monetary(
        string='Penalización',
        compute='_compute_new_plan',
        currency_field='currency_id',
        store=False,
        help="Penalización por refinanciar (según configuración)"
    )
    new_interest = fields.Monetary(
        string='Nuevos Intereses',
        compute='_compute_new_plan',
        currency_field='currency_id',
        store=False,
        help="Intereses generados por el nuevo plazo"
    )
    new_installment_value = fields.Monetary(
        string='Nuevo Valor Cuota',
        compute='_compute_new_plan',
        currency_field='currency_id',
        store=False,
        help="Valor de cada cuota mensual"
    )
    total_to_finance = fields.Monetary(
        string='Total a Financiar',
        compute='_compute_new_plan',
        currency_field='currency_id',
        store=False,
        help="Capital + Penalización + Intereses"
    )
    
    # ============================================
    # OTROS
    # ============================================
    
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id',
        readonly=True
    )
    
    notes = fields.Text(
        string='Notas',
        help="Observaciones sobre este refinanciamiento"
    )
    
    # ============================================
    # MÉTODOS DEFAULT
    # ============================================
    
    def _default_new_term(self):
        """Plazo default = cuotas pendientes actuales"""
        credit_id = self.env.context.get('active_id')
        if credit_id:
            credit = self.env['sale.credit'].browse(credit_id)
            pending = len(credit.credit_lines.filtered(lambda l: l.state == 'pending'))
            return pending
        return 12
    
    # ============================================
    # MÉTODOS COMPUTED
    # ============================================
    
    @api.depends('credit_id')
    def _compute_current_data(self):
        """Calcula datos actuales del crédito"""
        for wizard in self:
            if wizard.credit_id:
                pending_lines = wizard.credit_id.credit_lines.filtered(
                    lambda l: l.state == 'pending'
                )
                wizard.current_installments_pending = len(pending_lines)
                wizard.current_installment_value = pending_lines[0].amount_fixed if pending_lines else 0
            else:
                wizard.current_installments_pending = 0
                wizard.current_installment_value = 0
    
    @api.depends('capital_down_payment', 'new_term', 'new_category_id')
    def _compute_new_plan(self):
        """Calcula automáticamente el nuevo plan financiero"""
        for wizard in self:
            if wizard.credit_id and wizard.new_term > 0:
                # Usar los métodos del crédito para cálculos
                calc = wizard.credit_id._calc_new_installment_value(
                    wizard.new_term,
                    wizard.capital_down_payment
                )
                
                wizard.new_capital = calc['new_capital']
                wizard.penalty = calc['penalty']
                wizard.new_interest = calc['new_interest']
                wizard.total_to_finance = calc['total_to_finance']
                wizard.new_installment_value = calc['installment_value']
            else:
                wizard.new_capital = 0
                wizard.penalty = 0
                wizard.new_interest = 0
                wizard.total_to_finance = 0
                wizard.new_installment_value = 0
    
    # ============================================
    # VALIDACIONES (constraints)
    # ============================================
    
    @api.constrains('capital_down_payment')
    def _check_min_capital_down(self):
        """Valida monto mínimo de abono a capital según configuración"""
        for wizard in self:
            min_pct = float(
                self.env['ir.config_parameter'].sudo().get_param(
                    'cjg_finance.refinance_min_capital_down_pct', default='0.0'
                )
            )
            
            if min_pct > 0 and wizard.current_balance > 0:
                min_amount = wizard.current_balance * (min_pct / 100.0)
                if wizard.capital_down_payment < min_amount:
                    raise ValidationError(_(
                        "El abono a capital debe ser al menos %s%% del saldo actual.\n\n"
                        "Mínimo requerido: %s %s\n"
                        "Abono ingresado: %s %s\n\n"
                        "Configure este porcentaje en: Configuración → Créditos → "
                        "Abono Mínimo a Capital (%%)"
                    ) % (
                        min_pct,
                        wizard.currency_id.symbol,
                        '{:,.2f}'.format(min_amount),
                        wizard.currency_id.symbol,
                        '{:,.2f}'.format(wizard.capital_down_payment)
                    ))
    
    @api.constrains('new_term')
    def _check_shorter_term(self):
        """Valida si se permite plazo menor según configuración"""
        for wizard in self:
            allow_shorter = self.env['ir.config_parameter'].sudo().get_param(
                'cjg_finance.refinance_allow_shorter_term', default='False'
            ) == 'True'
            
            if not allow_shorter and wizard.new_term < wizard.current_installments_pending:
                raise ValidationError(_(
                    "No se permite refinanciar con un plazo menor al actual.\n\n"
                    "Plazo actual: %d meses\n"
                    "Plazo ingresado: %d meses\n\n"
                    "Para habilitar plazos menores, vaya a:\n"
                    "Configuración → Créditos → Permitir Plazo Menor en Refinanciamiento"
                ) % (wizard.current_installments_pending, wizard.new_term))
    
    @api.constrains('new_term')
    def _check_positive_term(self):
        """Valida que el plazo sea positivo"""
        for wizard in self:
            if wizard.new_term <= 0:
                raise ValidationError(_(
                    "El plazo debe ser mayor a 0 meses."
                ))
    
    @api.constrains('capital_down_payment')
    def _check_down_payment_not_exceed_balance(self):
        """Valida que el abono no exceda el saldo"""
        for wizard in self:
            if wizard.capital_down_payment > wizard.current_balance:
                raise ValidationError(_(
                    "El abono a capital no puede ser mayor al saldo actual.\n\n"
                    "Saldo actual: %s %s\n"
                    "Abono ingresado: %s %s"
                ) % (
                    wizard.currency_id.symbol,
                    '{:,.2f}'.format(wizard.current_balance),
                    wizard.currency_id.symbol,
                    '{:,.2f}'.format(wizard.capital_down_payment)
                ))
    
    # ============================================
    # ACCIÓN PRINCIPAL
    # ============================================
    
    def action_apply_refinance(self):
        """
        Aplica el refinanciamiento con los parámetros configurados
        y persiste el registro histórico en finance.refinancing.history.
        """
        self.ensure_one()

        # Validar que el crédito existe y está en estado correcto
        if not self.credit_id:
            raise UserError(_("No se encontró el crédito a refinanciar."))

        old_snapshot = {
            'old_balance': self.current_balance,
            'old_installments_pending': self.current_installments_pending,
            'old_installment_value': self.current_installment_value,
            'old_interest_rate': self.current_interest_rate,
            'capital_down_payment': self.capital_down_payment,
            'penalty_applied': self.penalty,
            'new_interest_generated': self.new_interest,
            'new_balance': self.total_to_finance,
            'new_installments': self.new_term,
            'new_installment_value': self.new_installment_value,
            'new_interest_rate': (
                self.new_category_id.percent_interest
                if self.new_category_id else self.current_interest_rate
            ),
        }

        # Aplicar nueva categoría/tasa si se cambió
        if self.new_category_id:
            self.credit_id.category_id = self.new_category_id

        # Iniciar proceso de refinanciamiento (ejecuta validaciones)
        self.credit_id.refinance()

        # Actualizar plazo
        self.credit_id.write({
            'term': self.new_term,
        })

        # Recalcular cuotas con nuevo plazo
        self.credit_id.compute_loan()

        # Aplicar pagos existentes
        self.credit_id.apply_existing_payments()

        # Persistir historial del refinanciamiento (audit trail)
        history = self.env['finance.refinancing.history'].create({
            'credit_id': self.credit_id.id,
            'notes': self.notes or False,
            **old_snapshot,
        })
        self._populate_history_lines(history)

        # Guardar notas si hay
        if self.notes:
            self.credit_id.message_post(
                body=_("Notas del refinanciamiento: %s") % self.notes
            )
        
        # Mensaje de éxito
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Refinanciamiento Exitoso'),
                'message': _(
                    'El crédito ha sido refinanciado correctamente.\n'
                    'Nuevo plazo: %d meses\n'
                    'Nuevo valor cuota: %s %s'
                ) % (
                    self.new_term,
                    self.currency_id.symbol,
                    '{:,.2f}'.format(self.new_installment_value)
                ),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Crédito Refinanciado'),
                    'view_mode': 'form',
                    'res_model': 'sale.credit',
                    'res_id': self.credit_id.id,
                    'target': 'current',
                },
            },
        }

    def _populate_history_lines(self, history):
        """Crea finance.refinancing.line a partir del nuevo plan generado."""
        self.ensure_one()
        Line = self.env['finance.refinancing.line']
        total = len(self.credit_id.credit_lines)
        for idx, line in enumerate(self.credit_id.credit_lines.sorted('expected_date_payment'), start=1):
            Line.create({
                'history_id': history.id,
                'number': '%02d/%02d' % (idx, total),
                'date_maturity': line.expected_date_payment,
                'description': line.internal_notes or '',
                'amount_quota': line.amount_fixed or 0.0,
                'balance': line.amount_residual or line.amount_fixed or 0.0,
            })
