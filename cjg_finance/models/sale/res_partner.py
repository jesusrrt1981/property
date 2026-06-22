from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, RedirectWarning, UserError
class SaleOrder(models.Model):

    _inherit = 'res.partner'
    
    # is_motorista defined in cjg_finance_pos
    # is_motorista = fields.Boolean(string='Es Motorista', default=False)

    credit_amount = fields.Monetary(compute='_credit_total', string="Importe del Crédito")
    credit_count = fields.Integer(string="Crédito", compute='_credit_total')
    credit_id = fields.Many2one('sale.credit', string='Credito')
    sale_credit_ids = fields.One2many('sale.credit', 'partner_id', string='Contratos')
    credit_state = fields.Selection(related="credit_id.state", string="Estado de Pago")
    journal_id = fields.Many2one('account.journal', string="Diario")
    sale_advanced = fields.Boolean(string="Financiar?", readonly=True)
    credit_preapproved = fields.Monetary(compute='_credit_balance', string="Crédito Pre-aprobado")
    credit_preapproved_valid= fields.Boolean(string="Fondo aprobados", readonly=True)
    # Historial de seguimiento por cliente (líneas de follow-up)
    followup_line_ids = fields.One2many('followup.sale.credit', 'partner_id', string='Historial de Seguimiento')

    # Vista unificada estilo Testarossa info.php: contratos + mantenimientos + deuda total
    maintenance_contract_ids = fields.One2many(
        'maintenance.contract', 'partner_id', string='Contratos de Mantenimiento')
    maintenance_count = fields.Integer(
        string='Mantenimientos', compute='_compute_unified_finance')
    pending_installments_count = fields.Integer(
        string='Cuotas Pendientes', compute='_compute_unified_finance')
    total_debt = fields.Monetary(
        string='Deuda Total', compute='_compute_unified_finance',
        help='Suma de cuotas pendientes en contratos activos + balances de mantenimiento')
    next_due_date = fields.Date(
        string='Próxima Cuota', compute='_compute_unified_finance',
        help='Fecha de la próxima cuota pendiente más antigua')

    @api.depends('sale_credit_ids', 'sale_credit_ids.credit_lines.state',
                 'sale_credit_ids.credit_lines.amount_residual',
                 'maintenance_contract_ids', 'maintenance_contract_ids.state')
    def _compute_unified_finance(self):
        Line = self.env['sale.credit.line']
        for partner in self:
            active_credits = partner.sale_credit_ids.filtered(
                lambda c: c.state not in ('cancelled', 'refuse', 'closed'))
            pending_lines = Line.search([
                ('credit_id', 'in', active_credits.ids),
                ('state', 'in', ('pending', 'paid_overdue', 'paid_reload')),
            ])
            partner.pending_installments_count = len(pending_lines)
            partner.total_debt = sum(pending_lines.mapped('amount_residual'))
            partner.next_due_date = min(
                pending_lines.mapped('expected_date_payment') or [False]
            ) or False
            partner.maintenance_count = len(
                partner.maintenance_contract_ids.filtered(lambda m: m.state == 'active')
            )

    def action_show_credits(self):
        """Smart button: lista de contratos del cliente."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Contratos - %s') % self.name,
            'res_model': 'sale.credit',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_show_maintenance_contracts(self):
        """Smart button: contratos de mantenimiento del cliente."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mantenimientos - %s') % self.name,
            'res_model': 'maintenance.contract',
            'view_mode': 'tree,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_show_pending_installments(self):
        """Smart button: cuotas pendientes del cliente (todos sus contratos)."""
        self.ensure_one()
        active_credits = self.sale_credit_ids.filtered(
            lambda c: c.state not in ('cancelled', 'refuse', 'closed'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cuotas Pendientes - %s') % self.name,
            'res_model': 'sale.credit.line',
            'view_mode': 'tree,form',
            'domain': [
                ('credit_id', 'in', active_credits.ids),
                ('state', 'in', ('pending', 'paid_overdue', 'paid_reload')),
            ],
        }

    def action_partner_quick_collect(self):
        """Cobrar al cliente: si tiene 1 contrato activo abre directo el cobro;
        si tiene varios, lista para que el cajero escoja."""
        self.ensure_one()
        active_credits = self.sale_credit_ids.filtered(lambda c: c.state == 'approved')
        if not active_credits:
            raise UserError(_(
                "El cliente %s no tiene contratos aprobados para cobrar."
            ) % self.name)
        if len(active_credits) == 1:
            return active_credits.action_open_quick_collect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Selecciona contrato a cobrar'),
            'res_model': 'sale.credit',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', active_credits.ids)],
            'context': {'default_partner_id': self.id},
        }

    def _credit_balance(self):
        for partner in self:
            client_credito = self.env['sale_credit.preaprovado'].search([('client', '=', partner.id)])
            client_balance = self.env['sale.credit'].search([('partner_id', '=', partner.id), ('state', 'not in', ['refuse', 'cancelled'])])
            if bool(client_credito):
                partner.credit_preapproved_valid = True
                list_balance = []
                for record in client_balance:
                    list_balance.append(record.total_sold)
                balance = (client_credito.credit_preapproved - sum(list_balance))
            else:
                partner.credit_preapproved_valid = False
                balance = 0
            
            partner.credit_preapproved = balance

    def action_show_requested_credit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'target': 'current',
            'name': 'Contratos del Cliente',
            'res_model': 'sale.credit',
            'view_mode': 'kanban,tree,form',
            'views': [
                [self.env.ref('cjg_finance.sale_credit_kanban_partner').id, 'kanban'],
                [False, 'tree'],
                [False, 'form'],
            ],
            'domain': [('partner_id', '=', self.id)],
            'context': {'search_default_partner_id': self.id},
        }

    @api.depends('sale_credit_ids')
    def _credit_total(self):
        for partner in self:
            credits = partner.sale_credit_ids
            partner.credit_amount = sum(credits.mapped('amount_total'))
            partner.credit_count = len(credits)
