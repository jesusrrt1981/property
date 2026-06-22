# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime


class SaleCreditPortfolio(models.Model):
    _name = 'sale.credit.portfolio'
    _description = 'Portfolio Mensual de Cartera de Créditos'
    _order = 'year desc, month desc, credit_id'
    _rec_name = 'display_name'

    # Identificación del periodo
    month = fields.Integer(
        string='Mes',
        required=True,
        help='Mes del snapshot de cartera (1-12)'
    )
    year = fields.Integer(
        string='Año',
        required=True,
        help='Año del snapshot de cartera'
    )
    
    # Relación con el crédito
    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato de Crédito',
        required=True,
        ondelete='cascade',
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        related='credit_id.partner_id',
        store=True,
        readonly=True
    )
    
    # Montos esperados vs cobrados
    expected_amount = fields.Monetary(
        string='Monto Esperado',
        currency_field='currency_id',
        help='Monto que debería haberse cobrado en este mes'
    )
    collected_amount = fields.Monetary(
        string='Monto Cobrado',
        currency_field='currency_id',
        help='Monto efectivamente cobrado en este mes'
    )
    balance = fields.Monetary(
        string='Saldo',
        currency_field='currency_id',
        compute='_compute_balance',
        store=True,
        help='Diferencia entre monto esperado y cobrado'
    )
    
    # Estado del contrato en este periodo
    status = fields.Selection([
        ('al_dia', 'Al Día'),
        ('mora', 'En Mora'),
        ('desistido', 'Desistido'),
        ('anulado', 'Anulado'),
        ('saldado', 'Saldado'),
    ], string='Estado', required=True, default='al_dia', index=True)
    
    # Información adicional
    installment_number = fields.Integer(
        string='Número de Cuota',
        help='Número de cuota correspondiente a este periodo'
    )
    late_fee = fields.Monetary(
        string='Mora',
        currency_field='currency_id',
        help='Mora acumulada en este periodo'
    )
    days_overdue = fields.Integer(
        string='Días de Atraso',
        help='Cantidad de días de atraso en este periodo'
    )
    
    # Clasificación del cliente (heredada de testarossa)
    client_classification = fields.Selection([
        ('A', 'Clase A - Premium'),
        ('B', 'Clase B - Regular'),
        ('C', 'Clase C - Riesgo')
    ], string='Clasificación Cliente', index=True)
    
    # Oficial de cobro responsable
    collector_id = fields.Many2one(
        'res.users',
        string='Oficial de Cobro',
        help='Usuario responsable del cobro en este periodo'
    )
    
    # Moneda
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        related='credit_id.currency_id',
        store=True,
        readonly=True
    )
    
    # Campos calculados
    display_name = fields.Char(
        string='Nombre',
        compute='_compute_display_name',
        store=True
    )
    period_key = fields.Char(
        string='Periodo',
        compute='_compute_period_key',
        store=True,
        index=True
    )
    
    # Campos de auditoría
    notes = fields.Text(string='Notas')
    create_date = fields.Datetime(string='Fecha Creación', readonly=True)
    write_date = fields.Datetime(string='Última Modificación', readonly=True)
    
    _sql_constraints = [
        ('unique_credit_period', 
         'UNIQUE(credit_id, year, month)',
         'Ya existe un registro de portfolio para este crédito y periodo!')
    ]
    
    @api.depends('expected_amount', 'collected_amount')
    def _compute_balance(self):
        """Calcular el balance (diferencia entre esperado y cobrado)"""
        for record in self:
            record.balance = record.expected_amount - record.collected_amount
    
    @api.depends('credit_id', 'year', 'month')
    def _compute_display_name(self):
        """Generar nombre descriptivo del registro"""
        for record in self:
            if record.credit_id and record.year and record.month:
                month_name = datetime(record.year, record.month, 1).strftime('%B')
                record.display_name = f"{record.credit_id.name} - {month_name} {record.year}"
            else:
                record.display_name = _('Nuevo Portfolio')
    
    @api.depends('year', 'month')
    def _compute_period_key(self):
        """Generar clave de periodo en formato YYYYMM"""
        for record in self:
            if record.year and record.month:
                record.period_key = f"{record.year}{record.month:02d}"
            else:
                record.period_key = False
    
    @api.constrains('month')
    def _check_month(self):
        """Validar que el mes esté entre 1 y 12"""
        for record in self:
            if record.month < 1 or record.month > 12:
                raise ValidationError(_('El mes debe estar entre 1 y 12'))
    
    @api.constrains('year')
    def _check_year(self):
        """Validar que el año sea razonable"""
        for record in self:
            current_year = datetime.now().year
            if record.year < 2000 or record.year > current_year + 10:
                raise ValidationError(
                    _('El año debe estar entre 2000 y %s') % (current_year + 10)
                )
    
    @api.model
    def generate_monthly_snapshot(self, month=None, year=None):
        """
        Generar snapshot de cartera para todos los créditos activos en un mes/año específico.
        Si no se especifica mes/año, usa el mes actual.
        
        :param month: Mes (1-12) o None para mes actual
        :param year: Año o None para año actual
        :return: Recordset de portfolio creados
        """
        if month is None or year is None:
            now = datetime.now()
            month = month or now.month
            year = year or now.year
        
        # Buscar créditos activos
        active_credits = self.env['sale.credit'].search([
            ('state', 'in', ['approved', 'running']),
        ])
        
        created_portfolios = self.env['sale.credit.portfolio']
        
        for credit in active_credits:
            # Verificar si ya existe un registro para este periodo
            existing = self.search([
                ('credit_id', '=', credit.id),
                ('year', '=', year),
                ('month', '=', month)
            ])
            
            if existing:
                continue
            
            # Buscar la cuota correspondiente a este periodo
            installment = self.env['sale.credit.installment'].search([
                ('credit_id', '=', credit.id),
                ('month', '=', month),
                ('year', '=', year)
            ], limit=1)
            
            # Determinar montos
            expected_amount = installment.amount if installment else 0.0
            collected_amount = installment.paid_amount if installment else 0.0
            
            # Determinar estado
            status = self._determine_status(credit, installment)
            
            # Determinar clasificación del cliente
            classification = self._determine_client_classification(credit, installment)
            
            # Crear registro de portfolio
            portfolio_vals = {
                'month': month,
                'year': year,
                'credit_id': credit.id,
                'expected_amount': expected_amount,
                'collected_amount': collected_amount,
                'status': status,
                'installment_number': installment.installment_number if installment else 0,
                'late_fee': installment.late_fee if installment else 0.0,
                'days_overdue': installment.days_overdue if installment else 0,
                'client_classification': classification,
                'collector_id': credit.user_id.id if credit.user_id else False,
            }
            
            portfolio = self.create(portfolio_vals)
            created_portfolios |= portfolio
        
        return created_portfolios
    
    def _determine_status(self, credit, installment):
        """Determinar el estado del crédito en este periodo"""
        if credit.state == 'cancelled':
            return 'anulado'
        elif credit.state == 'closed':
            return 'saldado'
        elif installment and installment.state == 'paid':
            return 'al_dia'
        elif installment and installment.days_overdue > 0:
            return 'mora'
        else:
            return 'al_dia'
    
    def _determine_client_classification(self, credit, installment):
        """
        Determinar la clasificación del cliente (A/B/C) basado en su comportamiento de pago.
        Esta lógica replica la clasificación del sistema Testarossa.
        
        A: Cliente premium - siempre paga a tiempo
        B: Cliente regular - ocasionalmente se atrasa
        C: Cliente riesgo - frecuentemente en mora
        """
        # Buscar historial de pagos
        paid_installments = self.env['sale.credit.installment'].search([
            ('credit_id', '=', credit.id),
            ('state', '=', 'paid')
        ])
        
        total_installments = len(paid_installments)
        if total_installments == 0:
            return 'C'
        
        # Contar cuántas cuotas se pagaron a tiempo
        on_time_count = len([i for i in paid_installments if i.days_overdue == 0])
        on_time_percentage = (on_time_count / total_installments) * 100
        
        # Clasificar
        if on_time_percentage >= 90:
            return 'A'
        elif on_time_percentage >= 70:
            return 'B'
        else:
            return 'C'
    
    @api.model
    def get_portfolio_summary(self, month=None, year=None):
        """
        Obtener resumen de cartera para un periodo específico.
        Usado para el dashboard.
        
        :return: Dict con métricas de cartera
        """
        if month is None or year is None:
            now = datetime.now()
            month = month or now.month
            year = year or now.year
        
        portfolios = self.search([
            ('year', '=', year),
            ('month', '=', month)
        ])
        
        summary = {
            'total_contracts': len(portfolios),
            'total_expected': sum(portfolios.mapped('expected_amount')),
            'total_collected': sum(portfolios.mapped('collected_amount')),
            'total_balance': sum(portfolios.mapped('balance')),
            'total_late_fee': sum(portfolios.mapped('late_fee')),
            'by_status': {},
            'by_classification': {},
            'by_collector': {},
        }
        
        # Agrupar por estado
        for status in ['al_dia', 'mora', 'desistido', 'anulado', 'saldado']:
            status_portfolios = portfolios.filtered(lambda p: p.status == status)
            summary['by_status'][status] = {
                'count': len(status_portfolios),
                'expected': sum(status_portfolios.mapped('expected_amount')),
                'collected': sum(status_portfolios.mapped('collected_amount')),
            }
        
        # Agrupar por clasificación
        for classification in ['A', 'B', 'C']:
            class_portfolios = portfolios.filtered(
                lambda p: p.client_classification == classification
            )
            summary['by_classification'][classification] = {
                'count': len(class_portfolios),
                'expected': sum(class_portfolios.mapped('expected_amount')),
                'collected': sum(class_portfolios.mapped('collected_amount')),
            }
        
        # Agrupar por oficial de cobro
        collectors = portfolios.mapped('collector_id')
        for collector in collectors:
            collector_portfolios = portfolios.filtered(
                lambda p: p.collector_id == collector
            )
            summary['by_collector'][collector.name] = {
                'count': len(collector_portfolios),
                'expected': sum(collector_portfolios.mapped('expected_amount')),
                'collected': sum(collector_portfolios.mapped('collected_amount')),
                'effectiveness': (
                    sum(collector_portfolios.mapped('collected_amount')) / 
                    sum(collector_portfolios.mapped('expected_amount')) * 100
                    if sum(collector_portfolios.mapped('expected_amount')) > 0 else 0
                ),
            }
        
        return summary
