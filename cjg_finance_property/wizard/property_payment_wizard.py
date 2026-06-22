# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import fields, models, api


class PropertyPayment(models.TransientModel):
    _name = 'property.payment.wizard'
    _description = 'Create Invoice For Rent'

    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)

    customer_id = fields.Many2one('res.partner', string='Customer', domain = "[('user_type', '=', 'customer')]")
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency')
    type = fields.Selection([('deposit', 'Deposit'),
                             ('maintenance', 'Maintenance'),
                             ('penalty', 'Penalty'),
                             ('extra_service', 'Extra Service'),
                             ('other', 'Other')],
                            string='Payment For')
    description = fields.Char(string='Description', translate=True)
    invoice_date = fields.Date(string='Date', default=fields.Date.today())
    amount = fields.Monetary(string='Amount')
    rent_invoice_id = fields.Many2one('account.move', string='Invoice')
    # service
    service_id = fields.Many2one('product.product', string="Service",
                                 default=lambda self: self.env.ref('cjg_finance_property.property_product_1',
                                                                   raise_if_not_found=False))
    tax_ids = fields.Many2many('account.tax', string="Taxes")

    is_invoice = fields.Boolean()
    is_bill = fields.Boolean()
    bill_type = fields.Char(string="Payment For ")

    # Default Get
    @api.model
    def default_get(self, fields):
        res = super(PropertyPayment, self).default_get(fields)
        current_context = self._context
        active_id = current_context.get('active_id')
        is_invoice = current_context.get('is_invoice')
        is_bill = current_context.get('is_bill')
        res['is_invoice'] = is_invoice
        res['is_bill'] = is_bill
        return res

    @api.onchange('type')
    def _onchange_type_service(self):
        for rec in self:
            if rec.type == 'extra_service':
                rec.service_id = False
            else:
                rec.service_id = self.env.ref(
                    'cjg_finance_property.property_product_1', raise_if_not_found=False)

    def property_payment_action(self):
        if self.type == 'extra_service':
            invoice_id = self.env['account.move'].sudo().create({
                'partner_id': self.customer_id.id,
                'move_type': 'out_invoice',
                'invoice_date': self.invoice_date,
                'invoice_line_ids': [(0, 0, {
                    'product_id': self.service_id.id,
                    'name': self.description,
                    'quantity': 1,
                    'price_unit': self.amount,
                    'tax_ids': self.tax_ids.ids
                })]
            })
            self.env['contract.extra.service.line'].sudo().create({
                'service_id': self.service_id.id,
                'price': invoice_id.amount_total,
                'invoice_id': invoice_id.id
            })
        else:
            self.process_contract_invoice()

    def process_contract_invoice(self):
        invoice_post_type = self.env['ir.config_parameter'].sudo(
        ).get_param('cjg_finance_property.invoice_post_type')
        invoice_id = self.env['account.move'].sudo().create({
            'partner_id': self.customer_id.id,
            'move_type': 'out_invoice',
            'invoice_date': self.invoice_date,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.service_id.id,
                'name': self.description,
                'quantity': 1,
                'price_unit': self.amount,
                'tax_ids': self.tax_ids.ids
            })]
        })
        if invoice_post_type == 'automatically':
            invoice_id.action_post()

    def property_bill_action(self):
        invoice_post_type = self.env['ir.config_parameter'].sudo(
        ).get_param('cjg_finance_property.invoice_post_type')
        data = {
            'partner_id': self.customer_id.id,
            'move_type': 'in_invoice',
            'invoice_date': self.invoice_date,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.service_id.id,
                'name': self.description,
                'quantity': 1,
                'price_unit': self.amount,
                'tax_ids': self.tax_ids.ids
            })]
        }
        bill_id = self.env['account.move'].sudo().create(data)
        if invoice_post_type == 'automatically':
            bill_id.action_post()
