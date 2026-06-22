# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleCreditCharge(models.Model):
    _name = 'sale.credit.charge'
    _description = 'Cargos y Abonos del Contrato'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    
    name = fields.Char(
        string='Referencia',
        required=True,
        copy=False,
        readonly=True,
        default='/',
        tracking=True
    )
    
    # Relaciones
    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        ondelete='cascade',
        tracking=True,
        index=True
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        related='credit_id.partner_id',
        string='Cliente',
        store=True,
        index=True
    )
    
    # Tipo de Cargo/Abono
    charge_type = fields.Selection([
        ('charge', 'Cargo'),
        ('credit', 'Abono'),
        ('reactivation_quota_adjustment', 'Ajuste de Cuota por Reactivación'),
    ], string='Tipo', required=True, default='charge', tracking=True)
    
    # Montos
    amount = fields.Monetary(
        string='Monto',
        required=True,
        currency_field='currency_id',
        tracking=True
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id',
        string='Moneda',
        store=True
    )
    
    # Fechas
    date = fields.Date(
        string='Fecha',
        default=fields.Date.today,
        required=True,
        tracking=True
    )
    
    # Motivo/Descripción
    reason = fields.Text(
        string='Motivo',
        required=True,
        tracking=True
    )
    
    # Estado
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('posted', 'Aplicado'),
        ('cancelled', 'Cancelado'),
    ], string='Estado', default='draft', required=True, tracking=True)
    
    # Metadata
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company,
        required=True
    )
    
    user_id = fields.Many2one(
        'res.users',
        string='Creado Por',
        default=lambda self: self.env.user,
        readonly=True
    )
    
    # Campo para migración (ID de Testarossa)
    testarossa_id = fields.Integer(
        string='ID Testarossa',
        help='ID del registro en balance_clientes de Testarossa',
        index=True
    )
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.credit.charge') or '/'
        return super(SaleCreditCharge, self).create(vals_list)
    
    def action_post(self):
        """Aplicar el cargo/abono"""
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError(_('Solo se pueden aplicar cargos/abonos en estado borrador.'))
        
        self.write({'state': 'posted'})
        
        # Recalcular balance del contrato
        self.credit_id._compute_charges()
        
        # Mensaje en el contrato
        charge_type_label = dict(self._fields['charge_type'].selection).get(self.charge_type)
        self.credit_id.message_post(
            body=_('%s aplicado: %s por %s') % (charge_type_label, self.currency_id.symbol + str(self.amount), self.reason),
            subject=_('Cargo/Abono Aplicado')
        )
        
        return True
    
    def action_cancel(self):
        """Cancelar el cargo/abono"""
        self.ensure_one()
        if self.state == 'cancelled':
            raise ValidationError(_('El cargo/abono ya está cancelado.'))
        
        self.write({'state': 'cancelled'})
        
        # Recalcular balance del contrato
        self.credit_id._compute_charges()
        
        return True
    
    def action_draft(self):
        """Volver a borrador"""
        self.write({'state': 'draft'})
        return True
    
    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_('El monto debe ser mayor a cero.'))
    
    def name_get(self):
        result = []
        for charge in self:
            charge_type = dict(self._fields['charge_type'].selection).get(charge.charge_type)
            name = f"{charge.name} - {charge_type} {charge.currency_id.symbol}{charge.amount}"
            result.append((charge.id, name))
        return result
