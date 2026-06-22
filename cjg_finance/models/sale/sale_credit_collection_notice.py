from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleCreditCollectionNotice(models.Model):
    _name = 'sale.credit.collection.notice'
    _description = 'Aviso de Cobro'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, name desc'

    name = fields.Char(
        string='Número de Aviso',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuevo')
    )
    
    date = fields.Date(
        string='Fecha de Emisión',
        default=fields.Date.context_today,
        required=True,
        tracking=True
    )
    
    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        tracking=True,
        domain="[('state', '=', 'approved')]"
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        related='credit_id.partner_id',
        store=True,
        readonly=True
    )
    
    collector_id = fields.Many2one(
        'res.partner',
        string='Motorizado',
        domain="[('is_motorista', '=', True)]",
        tracking=True,
        help="Motorizado asignado para entregar el aviso y realizar el cobro"
    )
    
    official_id = fields.Many2one(
        'res.users',
        string='Oficial de Cuenta',
        related='credit_id.oficial_id',
        store=True,
        readonly=True
    )
    
    line_ids = fields.One2many(
        'sale.credit.collection.notice.line',
        'notice_id',
        string='Detalle de Cobro'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id_money',
        readonly=True
    )
    
    amount_total = fields.Monetary(
        string='Total a Cobrar',
        compute='_compute_amount_total',
        store=True,
        currency_field='currency_id'
    )
    
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('assigned', 'Asignado'),
        ('delivered', 'Entregado'),
        ('collected', 'Cobrado'),
        ('cancelled', 'Cancelado')
    ], string='Estado', default='draft', tracking=True)
    
    notes = fields.Text(string='Notas')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.credit.collection.notice') or _('Nuevo')
        return super(SaleCreditCollectionNotice, self).create(vals_list)
    
    @api.depends('line_ids.amount')
    def _compute_amount_total(self):
        for record in self:
            record.amount_total = sum(line.amount for line in record.line_ids)
            
    def action_assign(self):
        for record in self:
            if not record.collector_id:
                raise ValidationError(_("Debe asignar un motorizado antes de continuar."))
            record.state = 'assigned'
            
    def action_print(self):
        return self.env.ref('cjg_finance.action_report_collection_notice').report_action(self)
        
    def action_mark_delivered(self):
        self.write({'state': 'delivered'})
        
    def action_mark_collected(self):
        self.write({'state': 'collected'})

class SaleCreditCollectionNoticeLine(models.Model):
    _name = 'sale.credit.collection.notice.line'
    _description = 'Línea de Aviso de Cobro'
    
    notice_id = fields.Many2one(
        'sale.credit.collection.notice',
        string='Aviso de Cobro',
        required=True,
        ondelete='cascade'
    )
    
    description = fields.Char(string='Descripción', required=True)
    
    amount = fields.Monetary(
        string='Monto',
        required=True,
        currency_field='currency_id'
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        related='notice_id.currency_id',
        readonly=True
    )
    
    credit_line_id = fields.Many2one(
        'sale.credit.line',
        string='Cuota Relacionada'
    )

class SaleCredit(models.Model):
    _inherit = 'sale.credit'
    
    collection_notice_ids = fields.One2many(
        'sale.credit.collection.notice',
        'credit_id',
        string='Avisos de Cobro'
    )
    
    collection_notice_count = fields.Integer(
        compute='_compute_collection_notice_count',
        string='Cantidad de Avisos'
    )
    
    @api.depends('collection_notice_ids')
    def _compute_collection_notice_count(self):
        for record in self:
            record.collection_notice_count = len(record.collection_notice_ids)
            
    def action_view_collection_notices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Avisos de Cobro'),
            'res_model': 'sale.credit.collection.notice',
            'view_mode': 'tree,form',
            'domain': [('credit_id', '=', self.id)],
            'context': {'default_credit_id': self.id}
        }
    
    def action_create_collection_notice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear Aviso de Cobro'),
            'res_model': 'sale.credit.collection.notice',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_credit_id': self.id,
                'default_official_id': self.oficial_id.id,
            }
        }
