# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import models, fields, api


class UserTypes(models.Model):
    _inherit = 'res.partner'

    user_type = fields.Selection([
                                  ('customer', 'Customer'),
                                  ('broker', 'Broker')],
                                 string='User Type')
    brokerage_company_id = fields.Many2one('res.company', string=' Brokerage Company',
                                           default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='brokerage_company_id.currency_id',
                                  string='Currency')

    # Customer Fields
    is_tenancy = fields.Boolean(string='Property Renting')
    is_sold_customer = fields.Boolean(string='Property Buyer')

    # Broker Fields
    property_sold_ids = fields.One2many('property.vendor', 'broker_id', string="Sold Commission")

    # Removed landlord-related counters and actions

