# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import models, fields, api


class ResCompany(models.Model):
    _inherit = 'res.company'

    default_longitude = fields.Char(string='Default Longitude')
    default_latitude = fields.Char(string='Default Latitude')


class RentalConfig(models.TransientModel):
    _inherit = 'res.config.settings'

    reminder_days = fields.Integer(string='Days', default=5,
                                   config_parameter='cjg_finance_property.reminder_days')
    sale_reminder_days = fields.Integer(string="Days ", default=3,
                                        config_parameter='cjg_finance_property.sale_reminder_days')
    invoice_post_type = fields.Selection([('manual', 'Invoice Post Manually'),
                                          ('automatically', 'Invoice Post Automatically')], string="Invoice Post",
                                         default='manual', config_parameter='cjg_finance_property.invoice_post_type')

    month_days = fields.Integer(string="Month Days",
                                default=30, config_parameter='cjg_finance_property.month_days')
    quarter_days = fields.Integer(string="Quarter Days",
                                  default=90, config_parameter='cjg_finance_property.quarter_days')
    year_days = fields.Integer(string="Year Days",
                               default=365, config_parameter='cjg_finance_property.year_days')

    # Default Account Product
    installment_item_id = fields.Many2one('product.product', string="Installment Item",
                                          default=lambda self: self.env.ref('cjg_finance_property.property_product_1',
                                                                            raise_if_not_found=False),
                                          config_parameter='cjg_finance_property.account_installment_item_id')
    deposit_item_id = fields.Many2one('product.product', string="Deposit Item",
                                      default=lambda self: self.env.ref('cjg_finance_property.property_product_2',
                                                                        raise_if_not_found=False),
                                      config_parameter='cjg_finance_property.account_deposit_item_id')
    broker_item_id = fields.Many2one('product.product', string="Broker Commission Item",
                                     default=lambda self: self.env.ref('cjg_finance_property.property_product_3',
                                                                       raise_if_not_found=False),
                                     config_parameter='cjg_finance_property.account_broker_item_id')
    maintenance_item_id = fields.Many2one('product.product', string="Maintenance Item",
                                          default=lambda self: self.env.ref('cjg_finance_property.property_product_4',
                                                                            raise_if_not_found=False),
                                          config_parameter='cjg_finance_property.account_maintenance_item_id')

    # Company coordinates (avoid "default_" prefix to prevent default_model requirement)
    company_latitude = fields.Char(related='company_id.default_latitude', readonly=False)
    company_longitude = fields.Char(related='company_id.default_longitude', readonly=False)
