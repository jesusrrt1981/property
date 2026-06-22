# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime
from dateutil.relativedelta import relativedelta

ELIGIBLE_LEGACY_STATUSES = (39, 59, 63)


class MaintenanceContract(models.Model):
    """
    Contratos de Mantenimiento Funerario
    Migrado desde balances_cliente_mto de Testarossa
    """
    _name = 'maintenance.contract'
    _description = 'Contrato de Mantenimiento Funerario'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, name'
    
    # Identificación
    name = fields.Char(
        string='Número de Contrato',
        required=True,
        copy=False,
        index=True,
        tracking=True
    )
    legacy_contract_number = fields.Char(
        string='Número Legacy',
        help='Número original del contrato en Testarossa',
        copy=False,
        index=True
    )
    
    # Cliente
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        required=True,
        tracking=True,
        index=True
    )
    partner_vat = fields.Char(
        string='RNC/Cédula',
        related='partner_id.vat',
        store=True,
        readonly=True
    )
    
    # Relación con contrato funerario original
    sale_credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato Funerario Original',
        help='Contrato de servicio funerario al que está asociado este mantenimiento',
        tracking=True
    )
    
    # Configuración del mantenimiento
    maintenance_fee = fields.Monetary(
        string='Cuota de Mantenimiento',
        required=True,
        tracking=True,
        currency_field='currency_id'
    )
    frequency = fields.Selection([
        ('monthly', 'Mensual'),
        ('quarterly', 'Trimestral'),
        ('biannual', 'Semestral'),
        ('yearly', 'Anual')
    ], string='Frecuencia de Pago',
       required=True,
       default='yearly',
       tracking=True,
       help='Frecuencia con la que se debe pagar el mantenimiento')
    
    # Fechas
    date_start = fields.Date(
        string='Fecha Inicio',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    date_end = fields.Date(
        string='Fecha Fin',
        tracking=True,
        help='Fecha de finalización del contrato (opcional - algunos contratos son perpetuos)'
    )
    next_payment_date = fields.Date(
        string='Próximo Pago',
        compute='_compute_next_payment_date',
        store=True,
        help='Fecha del próximo pago esperado'
    )
    
    # Estado y seguimiento
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('active', 'Activo'),
        ('suspended', 'Suspendido'),
        ('cancelled', 'Cancelado'),
        ('expired', 'Expirado')
    ], string='Estado',
       default='draft',
       required=True,
       tracking=True)
    
    # Pagos
    payment_ids = fields.One2many(
        'maintenance.contract.payment',
        'contract_id',
        string='Pagos de Mantenimiento'
    )
    payment_count = fields.Integer(
        string='# Pagos',
        compute='_compute_payment_count'
    )
    
    # Montos y saldos
    total_paid = fields.Monetary(
        string='Total Pagado',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id'
    )
    balance = fields.Monetary(
        string='Saldo Pendiente',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
        help='Saldo pendiente basado en pagos esperados vs recibidos'
    )
    
    # Moneda
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    use_manual_exchange_rate = fields.Boolean(
        string='Modificar Tasa?',
        default=False,
        tracking=True,
        help='Active este campo cuando el mantenimiento debe cobrarse con una tasa fija negociada.'
    )
    manual_exchange_rate = fields.Float(
        string='Tasa de Mantenimiento',
        digits=(16, 6),
        tracking=True,
        help='Tasa fija a usar en POS para convertir este mantenimiento a la moneda de caja.'
    )
    
    # Información adicional
    notes = fields.Text(string='Notas')
    user_id = fields.Many2one(
        'res.users',
        string='Responsable',
        default=lambda self: self.env.user,
        tracking=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        help='Compañía asociada (opcional)'
    )
    legacy_status_code = fields.Integer(
        string='Legacy Status Code',
        help='Exact Testarossa status used by annual maintenance eligibility rules.',
        index=True,
    )
    period_ids = fields.One2many('maintenance.period', 'contract_id', string='Annual Periods')
    
    _sql_constraints = [
        ('name_unique', 'UNIQUE(name, company_id)',
         'El número de contrato debe ser único por compañía!')
    ]

    @api.constrains('use_manual_exchange_rate', 'manual_exchange_rate')
    def _check_manual_exchange_rate(self):
        for record in self:
            if record.use_manual_exchange_rate and record.manual_exchange_rate <= 0.0:
                raise ValidationError(_('La tasa de mantenimiento debe ser mayor que cero cuando \"Modificar Tasa?\" está activo.'))

    def _get_exchange_company(self):
        self.ensure_one()
        return self.company_id or self.sale_credit_id.company_id or self.env.company

    def _get_pos_exchange_info(self, target_currency=None, date=None):
        """Return exchange metadata used by POS/Testarossa-style maintenance collections."""
        self.ensure_one()
        company = self._get_exchange_company()
        source_currency = self.currency_id or company.currency_id
        target_currency = target_currency or company.currency_id or self.env.company.currency_id
        date = date or fields.Date.context_today(self)

        if not source_currency or not target_currency or source_currency == target_currency:
            return {
                'source_currency': source_currency,
                'target_currency': target_currency,
                'rate': 1.0,
                'source': 'same',
                'is_manual': False,
            }

        if self.use_manual_exchange_rate and self.manual_exchange_rate > 0.0:
            rate = self.manual_exchange_rate
            source = 'manual'
            is_manual = True
        else:
            rate = source_currency._convert(1.0, target_currency, company, date)
            source = 'daily'
            is_manual = False

        return {
            'source_currency': source_currency,
            'target_currency': target_currency,
            'rate': rate,
            'source': source,
            'is_manual': is_manual,
        }

    def _convert_maintenance_amount_for_pos(self, amount, target_currency=None, date=None):
        self.ensure_one()
        exchange = self._get_pos_exchange_info(target_currency=target_currency, date=date)
        amount = float(amount or 0.0)
        source_currency = exchange['source_currency']
        target_currency = exchange['target_currency']
        if not source_currency or not target_currency or source_currency == target_currency:
            converted = amount
        elif exchange['is_manual']:
            converted = amount * exchange['rate']
        else:
            converted = source_currency._convert(amount, target_currency, self._get_exchange_company(), date or fields.Date.context_today(self))
        return target_currency.round(converted) if target_currency else round(converted, 2)
    
    @api.depends('payment_ids', 'payment_ids.state', 'payment_ids.amount')
    def _compute_amounts(self):
        """Calcular total pagado y saldo pendiente"""
        for record in self:
            # Total pagado = suma de pagos registrados
            posted_payments = record.payment_ids.filtered(
                lambda p: p.state == 'posted'
            )
            record.total_paid = sum(posted_payments.mapped('amount'))
            
            # Calcular saldo esperado según frecuencia
            if record.state == 'active' and record.date_start:
                expected_payments = record._calculate_expected_payments()
                expected_amount = expected_payments * record.maintenance_fee
                record.balance = expected_amount - record.total_paid
            else:
                record.balance = 0.0
    
    @api.depends('payment_ids')
    def _compute_payment_count(self):
        """Contar pagos"""
        for record in self:
            record.payment_count = len(record.payment_ids)
    
    @api.depends('frequency', 'date_start', 'payment_ids', 'payment_ids.payment_date')
    def _compute_next_payment_date(self):
        """Calcular fecha del próximo pago esperado"""
        for record in self:
            if record.state != 'active' or not record.date_start:
                record.next_payment_date = False
                continue
            
            # Obtener último pago
            last_payment = record.payment_ids.filtered(
                lambda p: p.state == 'posted'
            ).sorted('payment_date', reverse=True)[:1]
            
            if last_payment:
                base_date = last_payment.payment_date
            else:
                base_date = record.date_start
            
            # Calcular próxima fecha según frecuencia
            if record.frequency == 'monthly':
                record.next_payment_date = base_date + relativedelta(months=1)
            elif record.frequency == 'quarterly':
                record.next_payment_date = base_date + relativedelta(months=3)
            elif record.frequency == 'biannual':
                record.next_payment_date = base_date + relativedelta(months=6)
            elif record.frequency == 'yearly':
                record.next_payment_date = base_date + relativedelta(years=1)
            else:
                record.next_payment_date = False
    
    def _calculate_expected_payments(self):
        """Calcular número de pagos esperados desde fecha inicio hasta hoy"""
        self.ensure_one()
        
        if not self.date_start:
            return 0
        
        start = self.date_start
        today = fields.Date.context_today(self)
        
        if start > today:
            return 0
        
        # Calcular meses transcurridos
        months_elapsed = (today.year - start.year) * 12 + (today.month - start.month)
        
        # Según frecuencia
        if self.frequency == 'monthly':
            return months_elapsed + 1
        elif self.frequency == 'quarterly':
            return (months_elapsed // 3) + 1
        elif self.frequency == 'biannual':
            return (months_elapsed // 6) + 1
        elif self.frequency == 'yearly':
            return (months_elapsed // 12) + 1
        
        return 0
    
    def action_view_payments(self):
        """Abrir vista de pagos de este contrato"""
        self.ensure_one()
        return {
            'name': _('Pagos de Mantenimiento'),
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.contract.payment',
            'view_mode': 'tree,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {
                'default_contract_id': self.id,
                'default_partner_id': self.partner_id.id,
            }
        }
    
    def action_register_payment(self):
        """Abrir asistente para registrar pago"""
        self.ensure_one()
        return {
            'name': _('Registrar Pago'),
            'type': 'ir.actions.act_window',
            'res_model': 'maintenance.contract.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_partner_id': self.partner_id.id,
            }
        }
    
    def action_view_sale_credit_origin(self):
        """Smart button para ver contrato funerario origen"""
        self.ensure_one()
        if not self.sale_credit_id:
            return
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Contrato Funerario',
            'res_model': 'sale.credit',
            'view_mode': 'form',
            'res_id': self.sale_credit_id.id,
            'target': 'current'
        }
    
    def action_activate(self):
        """Activar contrato"""
        self.write({'state': 'active'})
    
    def action_suspend(self):
        """Suspender contrato"""
        self.write({'state': 'suspended'})
    
    def action_cancel(self):
        """Cancelar contrato"""
        self.write({'state': 'cancelled'})

    def _validate_annual_generation(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        company_code = (company.name or '').strip().upper()
        if company.testarossa_em_id != 1 and company_code not in ('PJM', '01'):
            raise ValidationError(_('Annual maintenance is only available for legacy company PJM/01.'))
        if self.state != 'active' or self.legacy_status_code not in ELIGIBLE_LEGACY_STATUSES:
            raise ValidationError(_('The contract status is not eligible for annual maintenance.'))
        if not self.date_start or self.maintenance_fee <= 0:
            raise ValidationError(_('A sale date and a maintenance fee greater than zero are required.'))

        if 'sale.credit.rcv' in self.env:
            active_rcv = self.env['sale.credit.rcv'].sudo().search([
                ('state', 'in', ('draft', 'issued')),
                '|',
                ('maintenance_payment_id.contract_id', '=', self.id),
                ('maintenance_period_id.contract_id', '=', self.id),
            ], limit=1)
            if active_rcv:
                raise ValidationError(_('Active maintenance RCV %s must be cancelled first.') % active_rcv.display_name)

    def generate_annual_periods(self, years):
        """Generate the next 1..5 annual charges atomically and without duplicate rows."""
        self.ensure_one()
        if not isinstance(years, int) or isinstance(years, bool) or not 1 <= years <= 5:
            raise ValidationError(_('Years must be an integer between 1 and 5.'))
        self._validate_annual_generation()
        Period = self.env['maintenance.period']
        with self.env.cr.savepoint():
            # Serialize generators for this contract.  The SQL uniqueness rule is
            # the final guard; this lock makes concurrent calls deterministic.
            self.env.cr.execute(
                'SELECT id FROM maintenance_contract WHERE id = %s FOR UPDATE',
                (self.id,),
            )
            created = Period.browse()
            existing = set(Period.search([
                ('contract_id', '=', self.id), ('concept_code', '=', '106'),
                ('sequence', '<=', years),
            ]).mapped('sequence'))
            for sequence in range(1, years + 1):
                if sequence in existing:
                    continue
                due_date = self.date_start + relativedelta(years=sequence)
                charge = self._create_annual_sequence(sequence, due_date)
                created |= charge
            return created

    def _create_annual_sequence(self, sequence, due_date):
        charge = self.env['maintenance.period'].create({
            'contract_id': self.id, 'sequence': sequence, 'due_date': due_date,
            'concept_code': '106', 'amount': self.maintenance_fee,
        })
        policy = self.env['maintenance.exemption.policy'].search([
            ('contract_id', '=', self.id), ('active', '=', True),
            ('date_from', '<=', due_date), ('date_to', '>=', due_date),
        ], order='date_from desc, id desc', limit=1)
        if policy:
            self.env['maintenance.period'].create({
                'contract_id': self.id, 'sequence': sequence, 'due_date': due_date,
                'concept_code': '204',
                'amount': -(self.maintenance_fee * policy.percentage / 100.0),
            })
        return charge

    def action_open_annual_generation_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Annual Maintenance'),
            'res_model': 'maintenance.period.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    @api.model
    def cron_generate_annual_periods(self):
        today = fields.Date.context_today(self)
        contracts = self.search([('state', '=', 'active'), ('date_start', '!=', False)])
        for contract in contracts:
            anniversary = contract.date_start + relativedelta(years=today.year - contract.date_start.year)
            if anniversary > today:
                continue
            sequence = today.year - contract.date_start.year
            if sequence < 1:
                continue
            try:
                with self.env.cr.savepoint():
                    contract._validate_annual_generation()
                    self.env.cr.execute(
                        'SELECT id FROM maintenance_contract WHERE id = %s FOR UPDATE',
                        (contract.id,),
                    )
                    existing = set(self.env['maintenance.period'].search([
                        ('contract_id', '=', contract.id), ('concept_code', '=', '106'),
                        ('sequence', '<=', sequence),
                    ]).mapped('sequence'))
                    for due_sequence in range(1, sequence + 1):
                        if due_sequence not in existing:
                            contract._create_annual_sequence(
                                due_sequence,
                                contract.date_start + relativedelta(years=due_sequence),
                            )
            except ValidationError:
                continue
    
    @api.model
    def cron_check_expired_contracts(self):
        """Cron para marcar contratos expirados"""
        today = fields.Date.context_today(self)
        expired = self.search([
            ('state', '=', 'active'),
            ('date_end', '!=', False),
            ('date_end', '<', today)
        ])
        expired.write({'state': 'expired'})


class MaintenanceContractPayment(models.Model):
    """
    Pagos de Contratos de Mantenimiento
    Migrado desde balances_cliente_mto de Testarossa
    """
    _name = 'maintenance.contract.payment'
    _description = 'Maintenance Payment (Extended from POS Receipt)'
    _inherit = ['cjg.pos.payment.receipt']
    _order = 'payment_date desc, id desc'
    _rec_name = 'display_name'
    
    # Relaciones
    contract_id = fields.Many2one(
        'maintenance.contract',
        string='Contrato de Mantenimiento',
        required=True,
        ondelete='cascade',
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        related='contract_id.partner_id',
        store=True,
        readonly=True
    )
    
    # Datos del pago (Mapeados a campos de recibo)
    amount = fields.Monetary(
        string='Monto',
        compute='_compute_amount',
        inverse='_set_amount',
        store=True,
        currency_field='currency_id'
    )
    payment_date = fields.Date(
        string='Fecha de Pago',
        compute='_compute_payment_date',
        inverse='_set_payment_date',
        store=True,
        index=True
    )
    legacy_payment_method_id = fields.Many2one(
        'account.payment.method',
        string='Método de Pago (Legacy)',
        help='Efectivo, transferencia, cheque, etc.'
    )
    cash_closing_id = fields.Many2one(
        'cash.box.closing',
        string='Cierre de Caja',
        ondelete='set null',
        index=True
    )
    
    # Referencia contable
    account_move_id = fields.Many2one(
        'account.move',
        string='Asiento Contable',
        help='Asiento contable generado por este pago',
        ondelete='restrict'
    )
    
    # Estado
    # Estado (Extendiendo los de POS Receipt)
    state = fields.Selection(selection_add=[
        ('posted', 'Registrado'),
    ], ondelete={'posted': 'cascade'})
    
    # Información adicional
    communication = fields.Char(string='Referencia/Memo')
    notes = fields.Text(string='Notas')
    
    # Legacy
    legacy_plan = fields.Integer(
        string='Plan Legacy',
        help='Número de plan en balance_clientes_mto de Testarossa'
    )
    
    # Moneda
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        related='contract_id.currency_id',
        default=None,
        store=True,
        readonly=True
    )

    @api.depends('amount_paid')
    def _compute_amount(self):
        for record in self:
            record.amount = record.amount_paid

    def _set_amount(self):
        for record in self:
            record.amount_paid = record.amount
            record.amount_total = record.amount

    @api.depends('date')
    def _compute_payment_date(self):
        for record in self:
            record.payment_date = record.date.date() if record.date else False

    def _set_payment_date(self):
        for record in self:
            if record.payment_date:
                # Si date es Datetime, necesitamos convertir Date a Datetime
                record.date = datetime.combine(record.payment_date, datetime.min.time())
    
    # Campos computados
    display_name = fields.Char(
        string='Nombre',
        compute='_compute_display_name',
        store=True
    )
    
    # Auditoría
    user_id = fields.Many2one(
        'res.users',
        string='Registrado Por',
        default=lambda self: self.env.user,
        readonly=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        compute='_compute_company_id',
        store=True,
        readonly=True
    )
    
    @api.depends('contract_id.company_id')
    def _compute_company_id(self):
        for record in self:
            record.company_id = record.contract_id.company_id
    
    @api.depends('contract_id', 'payment_date', 'amount')
    def _compute_display_name(self):
        """Generar nombre descriptivo"""
        for record in self:
            if record.contract_id and record.payment_date:
                record.display_name = f"{record.contract_id.name} - {record.payment_date} - ${record.amount:,.2f}"
            else:
                record.display_name = _('Nuevo Pago')
    
    def action_post(self):
        """Registrar pago y crear asiento contable via Herencia POS"""
        for record in self:
            if record.state != 'draft':
                raise ValidationError(_('Solo se pueden registrar pagos en borrador'))
            
            # Asegurar que el tipo de documento es mantenimiento
            if not record.document_type:
                record.document_type = 'maintenance'
            
            # Llamar al método de confirmación del padre (cjg.pos.payment.receipt)
            # que crea los asientos contables
            record.action_confirm()
            
            # Actualizar estado para compatibilidad legacy
            record.write({'state': 'posted'})
    
    def action_cancel(self):
        """Cancelar pago"""
        for record in self:
            if record.move_id and record.move_id.state == 'posted':
                raise ValidationError(
                    _('No se puede cancelar un pago con asiento contable registrado. '
                      'Primero debe revertir el asiento.')
                )
            record.write({'state': 'cancelled'})
