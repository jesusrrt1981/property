# -*- coding: utf-8 -*-

from odoo import models, fields, api


class SaleCreditExtended(models.Model):
    """
    Extensión del modelo sale.credit para soportar funcionalidades
    del sistema legacy Testarossa y tracking de portfolio
    """
    _inherit = 'sale.credit'
    
    # Campos legacy para migración desde Testarossa
    legacy_contract_number = fields.Char(
        string='Número de Contrato Legacy',
        help='Número original del contrato en el sistema Testarossa (PHP)',
        copy=False,
        index=True
    )
    
    # Tracking de portfolio mensual
    portfolio_month = fields.Integer(
        string='Mes Portfolio',
        help='Mes actual del portfolio de cartera (1-12)',
        compute='_compute_portfolio_period',
        store=True
    )
    portfolio_year = fields.Integer(
        string='Año Portfolio',
        help='Año actual del portfolio de cartera',
        compute='_compute_portfolio_period',
        store=True
    )
    
    # Clasificación del cliente (heredada de testarossa)
    client_classification = fields.Selection([
        ('A', 'Clase A - Premium'),
        ('B', 'Clase B - Regular'),
        ('C', 'Clase C - Riesgo')
    ], string='Clasificación Cliente',
       compute='_compute_client_classification',
       store=True,
       index=True,
       help='Clasificación del cliente basada en su historial de pagos')
    
    # Relación con registros de portfolio
    portfolio_ids = fields.One2many(
        'sale.credit.portfolio',
        'credit_id',
        string='Historial de Portfolio',
        help='Registros mensuales de portfolio para este crédito'
    )
    portfolio_count = fields.Integer(
        string='# Registros Portfolio',
        compute='_compute_portfolio_count'
    )
    
    # Estado actual del portfolio
    current_portfolio_status = fields.Selection([
        ('al_dia', 'Al Día'),
        ('mora', 'En Mora'),
        ('desistido', 'Desistido'),
        ('anulado', 'Anulado'),
        ('saldado', 'Saldado'),
    ], string='Estado Portfolio',
       compute='_compute_portfolio_status',
       store=True)
    
    @api.depends('state', 'credit_lines', 'credit_lines.state')
    def _compute_portfolio_period(self):
        """Calcular el periodo actual del portfolio"""
        from datetime import datetime
        for record in self:
            now = datetime.now()
            record.portfolio_month = now.month
            record.portfolio_year = now.year
    
    @api.depends('credit_lines', 'credit_lines.sale_credit_payment_ids', 'credit_lines.state', 'credit_lines.amount_paid_total')
    def _compute_client_classification(self):
        """
        Clasificar clientes según historial de pagos
        A: Excelente (>=90% pagos a tiempo)
        B: Bueno (>=70% pagos a tiempo)
        C: Regular (<70% pagos a tiempo)
        """
        for record in self:
            # Obtener todas las cuotas del crédito
            credit_lines = record.credit_lines.filtered(lambda l: l.state != 'cancelled')
            
            if not credit_lines:
                record.client_classification = 'B'  # Clasificación por defecto
                continue
            
            # Contar cuotas pagadas a tiempo vs totales
            total_lines = len(credit_lines)
            
            if total_lines == 0:
                record.client_classification = 'B'
                continue
            
            # Contar cuotas pagadas a tiempo (pagadas antes o en la fecha esperada)
            on_time_count = 0
            today = fields.Date.today()
            
            for line in credit_lines:
                if line.state == 'paid':
                    # Si está pagada, verificar si se pagó a tiempo
                    # Asumiendo que si está pagada y no tiene mora significativa, fue a tiempo
                    if line.date_payment and line.expected_date_payment:
                        if line.date_payment <= line.expected_date_payment:
                            on_time_count += 1
                    else:
                        # Si no hay fecha de pago registrada pero está marcada como pagada
                        # Consideramos que fue a tiempo
                        on_time_count += 1
            
            # Calcular porcentaje de cuotas pagadas a tiempo
            if total_lines > 0:
                percentage = (on_time_count / total_lines) * 100
                
                if percentage >= 90:
                    record.client_classification = 'A'
                elif percentage >= 70:
                    record.client_classification = 'B'
                else:
                    record.client_classification = 'C'
            else:
                record.client_classification = 'B'
    
    @api.depends('state', 'credit_lines', 'credit_lines.state')
    def _compute_portfolio_status(self):
        """Determinar el estado actual del crédito para el portfolio"""
        for record in self:
            if record.state == 'cancelled':
                record.current_portfolio_status = 'anulado'
            elif record.state == 'closed':
                record.current_portfolio_status = 'saldado'
            else:
                # Verificar si tiene cuotas en mora (usando credit_lines)
                # Asumimos que sale.credit.line tiene un campo para determinar mora
                # Si no tiene days_overdue, usamos expected_date_payment < today
                today = fields.Date.context_today(record)
                overdue_lines = record.credit_lines.filtered(
                    lambda l: l.state not in ['paid', 'cancel'] and l.expected_date_payment and l.expected_date_payment < today
                )
                
                if overdue_lines:
                    record.current_portfolio_status = 'mora'
                else:
                    record.current_portfolio_status = 'al_dia'
    
    @api.depends('portfolio_ids')
    def _compute_portfolio_count(self):
        """Contar registros de portfolio"""
        for record in self:
            record.portfolio_count = len(record.portfolio_ids)
    
    def action_view_portfolio(self):
        """Abrir vista de historial de portfolio para este crédito"""
        self.ensure_one()
        return {
            'name': _('Historial de Portfolio'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.portfolio',
            'view_mode': 'tree,form,pivot,graph',
            'domain': [('credit_id', '=', self.id)],
            'context': {
                'default_credit_id': self.id,
            }
        }
    
    def generate_current_portfolio_snapshot(self):
        """
        Generar snapshot de portfolio para el mes actual.
        Este método puede ser llamado manualmente o por un cron.
        """
        from datetime import datetime
        portfolio_model = self.env['sale.credit.portfolio']
        
        for credit in self:
            now = datetime.now()
            month = now.month
            year = now.year
            
            # Verificar si ya existe un snapshot para este mes
            existing = portfolio_model.search([
                ('credit_id', '=', credit.id),
                ('year', '=', year),
                ('month', '=', month)
            ])
            
            if existing:
                continue
            
            # Buscar la cuota correspondiente a este mes (usando credit_lines)
            # Asumimos que expected_date_payment determina el mes
            line = credit.credit_lines.filtered(
                lambda l: l.expected_date_payment and l.expected_date_payment.month == month and l.expected_date_payment.year == year
            )
            
            # Si hay múltiples líneas en el mes, tomamos la primera o sumamos
            # Por simplicidad tomamos la primera encontrada
            current_line = line[0] if line else False
            
            if not current_line:
                # Si no hay cuota para este mes, intentamos buscar la próxima pendiente
                # o simplemente no creamos snapshot si la lógica es estricta por mes
                continue
            
            # Calcular días de atraso
            days_overdue = 0
            if current_line.expected_date_payment and current_line.expected_date_payment < fields.Date.today() and current_line.state != 'paid':
                days_overdue = (fields.Date.today() - current_line.expected_date_payment).days
            
            # Crear snapshot
            portfolio_vals = {
                'month': month,
                'year': year,
                'credit_id': credit.id,
                'expected_amount': current_line.amount_fixed if current_line else 0.0,
                'collected_amount': current_line.amount_paid_total if current_line else 0.0,
                'status': credit.current_portfolio_status,
                'installment_number': current_line.count if current_line else 0,
                'late_fee': 0.0, # Placeholder si no hay campo directo
                'days_overdue': days_overdue,
                'client_classification': credit.client_classification,
                'collector_id': credit.user_id.id if credit.user_id else False,
            }
            
            portfolio_model.create(portfolio_vals)
        
        return True
