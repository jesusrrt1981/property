# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime

class CashBoxClosing(models.Model):
    _name = 'cash.box.closing'
    _description = 'Cierre de Caja'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_closing desc, id desc'

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, index=True, default=lambda self: _('New'))
    user_id = fields.Many2one('res.users', string='Cajero', default=lambda self: self.env.user, required=True, tracking=True)
    date_closing = fields.Datetime(string='Fecha de Cierre', default=fields.Datetime.now, required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company, required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('closed', 'Cerrado')
    ], string='Estado', default='draft', required=True, tracking=True)
    
    notes = fields.Text(string='Notas')
    
    # Relaciones con pagos
    payment_ids = fields.One2many('sale.credit.payment', 'cash_closing_id', string='Pagos de Crédito')
    maintenance_payment_ids = fields.One2many('maintenance.contract.payment', 'cash_closing_id', string='Pagos de Mantenimiento')
    
    # Totales
    total_amount = fields.Monetary(string='Total General', compute='_compute_totals', store=True, currency_field='currency_id')
    total_cash = fields.Monetary(string='Total Efectivo', compute='_compute_totals', store=True, currency_field='currency_id')
    total_card = fields.Monetary(string='Total Tarjeta', compute='_compute_totals', store=True, currency_field='currency_id')
    total_transfer = fields.Monetary(string='Total Transferencia', compute='_compute_totals', store=True, currency_field='currency_id')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('cash.box.closing') or _('New')
        return super(CashBoxClosing, self).create(vals_list)
    
    @api.depends('payment_ids', 'maintenance_payment_ids')
    def _compute_totals(self):
        for record in self:
            total = 0.0
            cash = 0.0
            card = 0.0
            transfer = 0.0
            
            # Sumar pagos de crédito
            for payment in record.payment_ids:
                total += payment.amount_total
                # Asumiendo que el diario determina el método (se puede refinar si hay campo method)
                # Por ahora simplificado, idealmente sale.credit.payment debería tener payment_method_id o similar
                # Si no existe, usaremos el tipo de diario
                if payment.journal_id.type == 'cash':
                    cash += payment.amount_total
                elif payment.journal_id.type == 'bank':
                    # Asumimos banco como transferencia o tarjeta, por ahora transferencia
                    transfer += payment.amount_total
            
            # Sumar pagos de mantenimiento
            for payment in record.maintenance_payment_ids:
                total += payment.amount
                if payment.journal_id.type == 'cash':
                    cash += payment.amount
                elif payment.journal_id.type == 'bank':
                    transfer += payment.amount
            
            record.total_amount = total
            record.total_cash = cash
            record.total_card = card # Implementar si se distinguen tarjetas
            record.total_transfer = transfer

    def action_load_payments(self):
        """Carga pagos del usuario actual que no estén en otro cierre"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se pueden cargar pagos en estado borrador.'))
            
        # Buscar pagos de crédito
        credit_payments = self.env['sale.credit.payment'].search([
            ('create_uid', '=', self.user_id.id),
            ('cash_closing_id', '=', False),
            ('company_id', '=', self.company_id.id),
            ('payment_date', '<=', self.date_closing.date()) # Solo hasta la fecha de cierre
        ])
        
        # Buscar pagos de mantenimiento
        maintenance_payments = self.env['maintenance.contract.payment'].search([
            ('create_uid', '=', self.user_id.id),
            ('cash_closing_id', '=', False),
            ('company_id', '=', self.company_id.id),
            ('payment_date', '<=', self.date_closing.date())
        ])
        
        self.payment_ids = [(6, 0, credit_payments.ids)]
        self.maintenance_payment_ids = [(6, 0, maintenance_payments.ids)]
        
        return True

    def action_close(self):
        """Cierra la caja y valida los pagos"""
        self.ensure_one()
        if not self.payment_ids and not self.maintenance_payment_ids:
            raise UserError(_('No hay pagos para cerrar.'))
            
        self.state = 'closed'
        return True
        
    def action_print_report(self):
        """Imprimir reporte de cierre"""
        self.ensure_one()
        return self.env.ref('cjg_finance.action_report_cash_box_closing').report_action(self)
