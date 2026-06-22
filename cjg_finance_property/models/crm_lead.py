# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import api, fields, models


class PropertyInquiry(models.Model):
    _inherit = 'crm.lead'

    property_id = fields.Many2one('property.details', string='Property',
                                  domain="['|',('stage','=','available'),('stage','=','sale')]")
    sale_lease = fields.Selection(related='property_id.sale_lease')
    price = fields.Monetary(related="property_id.price")

    # For sale
    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency ')
    ask_price = fields.Monetary(string="Ask Price")

    booking_id = fields.Many2one("property.vendor", string="Booking")
    
    sale_inquiry_id = fields.Many2one('sale.inquiry', string="Sale Enquiry")
