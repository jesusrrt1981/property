# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleCreditAdjustment(models.Model):
    _name = 'sale.credit.adjustment'
    _description = 'Ajustes de Crédito (Notas de Crédito/Débito)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Número',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('Nuevo')
    )
    
    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        ondelete='cascade',
        tracking=True
    )
    
    credit_line_id = fields.Many2one(
        'sale.credit.line',
        string='Línea de Crédito',
        domain="[('credit_id', '=', credit_id)]",
        help="Línea específica a ajustar. Si se deja vacío, se aplicará a la próxima cuota pendiente"
    )
    
    adjustment_type = fields.Selection([
        ('credit_note', 'Nota de Crédito'),
        ('debit_note', 'Nota de Débito'),
    ], string='Tipo de Ajuste', required=True, tracking=True)
    
    amount = fields.Float(
        string='Monto',
        required=True,
        digits=(12, 2),
        tracking=True
    )
    
    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    
    reason = fields.Text(
        string='Motivo',
        required=True,
        tracking=True
    )
    
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmed', 'Confirmado'),
        ('cancelled', 'Cancelado'),
    ], string='Estado', default='draft', tracking=True)
    
    user_id = fields.Many2one(
        'res.users',
        string='Usuario',
        default=lambda self: self.env.user,
        readonly=True
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        related='credit_id.company_id',
        store=True,
        readonly=True
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id_money',
        store=True,
        readonly=True
    )
    
    # Campos de migración
    testarossa_dcmto = fields.Char(
        string='Documento Testarossa',
        help='Número de documento original de Testarossa (balance_clientes.dcmto)'
    )
    
    testarossa_plan = fields.Char(
        string='Plan Testarossa',
        help='Número de plan original de Testarossa (balance_clientes.plan)'
    )
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                if vals.get('adjustment_type') == 'credit_note':
                    vals['name'] = self.env['ir.sequence'].next_by_code('sale.credit.adjustment.credit') or _('Nuevo')
                else:
                    vals['name'] = self.env['ir.sequence'].next_by_code('sale.credit.adjustment.debit') or _('Nuevo')
        return super(SaleCreditAdjustment, self).create(vals_list)
    
    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_('El monto debe ser mayor que cero.'))
    
    def action_confirm(self):
        """Confirmar el ajuste y aplicarlo a la línea de crédito"""
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Solo se pueden confirmar ajustes en estado borrador.'))
            
            # Buscar la línea a ajustar
            if not record.credit_line_id:
                # Si no se especificó línea, buscar la próxima cuota pendiente
                line = self.env['sale.credit.line'].search([
                    ('credit_id', '=', record.credit_id.id),
                    ('state', '=', 'pending')
                ], order='count asc', limit=1)
                
                if not line:
                    raise UserError(_('No se encontró ninguna cuota pendiente para aplicar el ajuste.'))
                
                record.credit_line_id = line.id
            
            line = record.credit_line_id
            
            # Aplicar el ajuste
            if record.adjustment_type == 'credit_note':
                # Nota de Crédito: Reduce la deuda
                new_residual = line.amount_residual - record.amount
                if new_residual < 0:
                    raise UserError(_(
                        'El monto de la nota de crédito (RD$ %s) es mayor que el saldo pendiente (RD$ %s).'
                    ) % (record.amount, line.amount_residual))
                
                line.write({
                    'amount_residual': new_residual,
                    'amount_paid_total': line.amount_paid_total + record.amount
                })
                
                # Si la cuota queda en 0, marcarla como pagada
                if new_residual == 0:
                    line.write({'state': 'paid'})
                
            else:
                # Nota de Débito: Aumenta la deuda
                line.write({
                    'amount_residual': line.amount_residual + record.amount,
                    'amount_fixed': line.amount_fixed + record.amount
                })
            
            # Cambiar estado a confirmado
            record.write({'state': 'confirmed'})
            
            # Mensaje en el contrato
            record.credit_id.message_post(
                body=_('<b>%s Aplicada</b><br/>'
                       'Monto: RD$ %s<br/>'
                       'Cuota: #%s<br/>'
                       'Motivo: %s') % (
                    'Nota de Crédito' if record.adjustment_type == 'credit_note' else 'Nota de Débito',
                    record.amount,
                    line.count,
                    record.reason
                ),
                subject=_('Ajuste Aplicado')
            )
    
    def action_cancel(self):
        """Cancelar el ajuste"""
        for record in self:
            if record.state == 'cancelled':
                raise UserError(_('El ajuste ya está cancelado.'))
            
            if record.state == 'confirmed':
                raise UserError(_(
                    'No se puede cancelar un ajuste confirmado. '
                    'Debe crear un ajuste inverso.'
                ))
            
            record.write({'state': 'cancelled'})
    
    def action_draft(self):
        """Volver a borrador"""
        for record in self:
            if record.state != 'cancelled':
                raise UserError(_('Solo se pueden volver a borrador los ajustes cancelados.'))
            
            record.write({'state': 'draft'})
