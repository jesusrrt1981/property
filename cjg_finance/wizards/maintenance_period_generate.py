# -*- coding: utf-8 -*-

from odoo import fields, models
from odoo.exceptions import ValidationError


class MaintenancePeriodGenerateWizard(models.TransientModel):
    _name = 'maintenance.period.generate.wizard'
    _description = 'Generate Annual Maintenance Periods'

    contract_id = fields.Many2one('maintenance.contract', required=True, readonly=True)
    years = fields.Integer(string='Generate through anniversary year', default=1, required=True)

    def action_generate(self):
        self.ensure_one()
        if not 1 <= self.years <= 5:
            raise ValidationError('Years must be between 1 and 5.')
        self.contract_id.generate_annual_periods(self.years)
        return {'type': 'ir.actions.act_window_close'}
