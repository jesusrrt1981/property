# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import api, fields, models, _


class PropertyExchangeRateWizard(models.TransientModel):
    _name = 'property.exchange.rate.wizard'
    _description = 'Apply exchange rate to units'

    apply_scope = fields.Selection([
        ('project', 'Project'),
        ('subproject', 'Subproject'),
    ], string='Scope', default='subproject', required=True)

    property_project_id = fields.Many2one('property.project', string='Project')
    property_sub_project_id = fields.Many2one('property.sub.project', string='Subproject')

    stage = fields.Selection([
        ('draft', 'Draft'),
        ('available', 'Available'),
        ('booked', 'In Booking'),
        ('sale', 'In Sale'),
        ('sold', 'Sold'),
    ], string='Unit Stage', default='available', required=True)

    foreign_currency_id = fields.Many2one('res.currency', string='Foreign Currency', required=True)
    exchange_rate = fields.Float(string='Exchange Rate', required=True,
                                 help='Company amount = foreign amount * exchange rate')

    unit_count = fields.Integer(string='Units to update', compute='_compute_unit_count')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')
        if active_model == 'property.project' and active_id:
            res['apply_scope'] = 'project'
            res['property_project_id'] = active_id
        elif active_model == 'property.sub.project' and active_id:
            res['apply_scope'] = 'subproject'
            res['property_sub_project_id'] = active_id
        # Defaults from the source record
        if active_model in ('property.project', 'property.sub.project') and active_id:
            rec = self.env[active_model].browse(active_id)
            if getattr(rec, 'foreign_currency_id', False):
                res['foreign_currency_id'] = rec.foreign_currency_id.id
            if getattr(rec, 'exchange_rate', False):
                res['exchange_rate'] = rec.exchange_rate
        return res

    def _compute_unit_count(self):
        Property = self.env['property.details']
        for wiz in self:
            domain = [('stage', '=', wiz.stage)]
            if wiz.apply_scope == 'project' and wiz.property_project_id:
                domain += [('property_project_id', '=', wiz.property_project_id.id)]
            elif wiz.apply_scope == 'subproject' and wiz.property_sub_project_id:
                domain += [('subproject_id', '=', wiz.property_sub_project_id.id)]
            wiz.unit_count = Property.search_count(domain)

    def action_apply(self):
        self.ensure_one()
        Property = self.env['property.details']
        domain = [('stage', '=', self.stage)]
        if self.apply_scope == 'project' and self.property_project_id:
            domain += [('property_project_id', '=', self.property_project_id.id)]
        elif self.apply_scope == 'subproject' and self.property_sub_project_id:
            domain += [('subproject_id', '=', self.property_sub_project_id.id)]
        units = Property.search(domain)
        if units:
            units.write({
                'foreign_currency_id': self.foreign_currency_id.id,
                'exchange_rate': self.exchange_rate,
            })
        return {'type': 'ir.actions.act_window_close'}