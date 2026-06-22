# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class ResCompanyAccounting(models.Model):
    """
    Extensión de res.company para configuración de cuentas contables
    y configuración general de créditos
    """
    _inherit = 'res.company'
    
    # Configuración General de Créditos (campos existentes en config.settings)
    credit_flow = fields.Selection([
        ('draft', 'Borrador'),
        ('confirm', 'Confirmar'),
        ('approve', 'Aprobar'),
    ], string='Flujo de Crédito', default='draft')
    
    overdue_type_credit = fields.Selection([
        ('simple', 'Simple'),
        ('compound', 'Compuesto'),
    ], string='Tipo de Mora de Crédito', default='simple')
    
    importe = fields.Float(string='Importe de Mora', default=0.0)
    porcentaje = fields.Float(string='Porcentaje de Mora %', default=0.0)
    
    overdue_type = fields.Selection([
        ('amount', 'Monto'),
        ('percent', 'Porcentaje'),
    ], string='Tipo de Mora', default='percent')
    
    overdue_type_apply = fields.Selection([
        ('auto', 'Automático'),
        ('manual', 'Manual'),
    ], string='Aplicación de Mora', default='auto')
    
    credit_cron_limit = fields.Char(string='Límite Cron Crédito', default='100')
    payment_cron_limit = fields.Char(string='Límite Cron Pago', default='100')
    split_credit_process = fields.Boolean(string='Dividir Proceso', default=False)
    
    credit_overdue = fields.Float(string='Moras de Crédito', default=0.0)
    
    manager_ids = fields.Many2many(
        'res.users',
        'company_credit_manager_rel',
        'company_id',
        'user_id',
        string='Gerentes de Crédito'
    )
    
    overdue_allowed_amount = fields.Float(string='Deuda Mayor A', default=0.0)
    overdue_invoice_limit = fields.Integer(string='Límite Máximo de Moras', default=3)
    
    overdue_period = fields.Selection([
        ('daily', 'Diario'),
        ('weekly', 'Semanal'),
        ('monthly', 'Mensual'),
    ], string='Frecuencia de Moras', default='monthly')
    
    payment_mail = fields.Char(string='Email de Pago')
    payment_phone = fields.Char(string='Teléfono de Pago')
    
    product_interest = fields.Many2one('product.product', string='Producto Interés')
    product_overdue = fields.Many2one('product.product', string='Producto Mora')
    
    term_and_conditions = fields.Html(string='Términos y Condiciones')
    
    credit_journal_id = fields.Many2one('account.journal', string='Diario Préstamos')
    credit_account_receivable_id = fields.Many2one('account.account', string='Cuenta Por Cobrar')
    credit_account_advanced_id = fields.Many2one('account.account', string='Cuenta de Avance')
    credit_earning_id = fields.Many2one('account.account', string='Cuenta de Ingreso')
    
    # Cuentas para Créditos (nuevas - integración contable)
    credit_income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de Ingreso por Créditos',
        domain="[('account_type', '=', 'income'), ('company_id', '=', id)]",
        help='Cuenta contable para registrar ingresos por pagos de créditos'
    )
    credit_cash_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de Caja para Créditos',
        domain="[('account_type', 'in', ['asset_cash', 'asset_current']), ('company_id', '=', id)]",
        help='Cuenta contable de caja/banco para recibir pagos de créditos'
    )
    credit_payment_journal_id = fields.Many2one(
        'account.journal',
        string='Diario de Pagos de Créditos',
        domain="[('type', 'in', ['cash', 'bank']), ('company_id', '=', id)]",
        help='Diario contable para registrar pagos de créditos'
    )
    
    # Cuentas para Mantenimiento
    maintenance_income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de Ingreso por Mantenimiento',
        domain="[('account_type', '=', 'income'), ('company_id', '=', id)]",
        help='Cuenta contable para registrar ingresos por mantenimiento'
    )
    maintenance_cash_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de Caja para Mantenimiento',
        domain="[('account_type', 'in', ['asset_cash', 'asset_current']), ('company_id', '=', id)]",
        help='Cuenta contable de caja/banco para recibir pagos de mantenimiento'
    )
    maintenance_payment_journal_id = fields.Many2one(
        'account.journal',
        string='Diario de Pagos de Mantenimiento',
        domain="[('type', 'in', ['cash', 'bank']), ('company_id', '=', id)]",
        help='Diario contable para registrar pagos de mantenimiento'
    )


class ResConfigSettingsAccounting(models.TransientModel):
    """
    Configuración de cuentas contables en ajustes
    """
    _inherit = 'res.config.settings'
    
    # Créditos
    credit_income_account_id = fields.Many2one(
        related='company_id.credit_income_account_id',
        readonly=False,
        string='Cuenta de Ingreso (Créditos)'
    )
    credit_cash_account_id = fields.Many2one(
        related='company_id.credit_cash_account_id',
        readonly=False,
        string='Cuenta de Caja (Créditos)'
    )
    credit_payment_journal_id = fields.Many2one(
        related='company_id.credit_payment_journal_id',
        readonly=False,
        string='Diario de Pagos (Créditos)'
    )
    
    # Mantenimiento
    maintenance_income_account_id = fields.Many2one(
        related='company_id.maintenance_income_account_id',
        readonly=False,
        string='Cuenta de Ingreso (Mantenimiento)'
    )
    maintenance_cash_account_id = fields.Many2one(
        related='company_id.maintenance_cash_account_id',
        readonly=False,
        string='Cuenta de Caja (Mantenimiento)'
    )
    maintenance_payment_journal_id = fields.Many2one(
        related='company_id.maintenance_payment_journal_id',
        readonly=False,
        string='Diario de Pagos (Mantenimiento)'
    )
