# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class MaintenancePeriod(models.Model):
    """Annual maintenance debt ledger; POS receipts remain settlement documents."""

    _name = 'maintenance.period'
    _description = 'Annual Maintenance Period'
    _order = 'contract_id, sequence, concept_code'

    contract_id = fields.Many2one('maintenance.contract', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one(related='contract_id.partner_id', store=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    sequence = fields.Integer(required=True, index=True)
    due_date = fields.Date(required=True, index=True)
    concept_code = fields.Selection([('106', 'Annual maintenance'), ('204', 'Maintenance exemption')], required=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    state = fields.Selection([('pending', 'Pending'), ('paid', 'Paid'), ('cancelled', 'Cancelled')], default='pending', required=True)
    payment_id = fields.Many2one('maintenance.contract.payment', ondelete='set null', copy=False)
    legacy_id = fields.Integer(index=True, copy=False)

    _sql_constraints = [
        ('contract_sequence_concept_unique', 'unique(contract_id, sequence, concept_code)',
         'This annual maintenance movement already exists.'),
        ('amount_sign_by_concept',
         "check((concept_code = '106' and amount > 0) or (concept_code = '204' and amount < 0))",
         'Charges must be positive and exemptions negative.'),
    ]

    def mark_paid(self, payment):
        self.ensure_one()
        rows = self.search([
            ('contract_id', '=', self.contract_id.id),
            ('sequence', '=', self.sequence),
            ('state', '=', 'pending'),
        ])
        rows.write({
            'state': 'paid', 'payment_id': payment.id,
        })

    def net_collectible(self):
        self.ensure_one()
        rows = self.search([
            ('contract_id', '=', self.contract_id.id),
            ('sequence', '=', self.sequence),
            ('state', '=', 'pending'),
        ])
        return max(sum(rows.mapped('amount')), 0.0)


class MaintenanceExemptionPolicy(models.Model):
    _name = 'maintenance.exemption.policy'
    _description = 'Maintenance Exemption Policy'
    _order = 'date_from desc, id desc'

    name = fields.Char(required=True)
    contract_id = fields.Many2one('maintenance.contract', required=True, ondelete='cascade', index=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    percentage = fields.Float(default=100.0, required=True)
    active = fields.Boolean(default=True)

    @api.constrains('date_from', 'date_to', 'percentage')
    def _check_policy(self):
        for policy in self:
            if policy.date_from > policy.date_to or not 0 < policy.percentage <= 100:
                from odoo.exceptions import ValidationError
                raise ValidationError(_('Exemption dates and percentage are invalid.'))
