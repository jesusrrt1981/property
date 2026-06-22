# -*- coding: utf-8 -*-
# Copyright 2025 CJG

import datetime
from dateutil.relativedelta import relativedelta
from odoo import fields, api, models, _


class TenancyInvoice(models.Model):
    _inherit = 'account.move'


    sold_id = fields.Many2one('property.vendor',
                              string="Sold Information",
                              readonly=True,
                              store=True)

    sold_property_id = fields.Many2one(related="sold_id.property_id",
                                       string="Property ")
    maintenance_request_id = fields.Many2one(
        'maintenance.request', string="Maintenance Ref.")


class PropertyVendor(models.Model):
    _name = 'property.vendor'
    _description = 'Stored Data About Sold Property'
    _rec_name = 'sold_seq'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Sale Contract Details
    sold_seq = fields.Char(string='Sequence', required=True,
                           readonly=True, copy=False, default=lambda self: _('New'))
    stage = fields.Selection([('booked', 'Booked'), ('refund', 'Refund'), (
        'sold', 'Sold'), ('cancel', 'Cancel'), ('locked', 'Locked')], string='Stage')
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', string='Currency')
    date = fields.Date(string='Create Date', default=fields.Date.today())
    
    broker_id = fields.Many2one('res.partner', string='Broker', domain=[('user_type', '=', 'broker')])
    # Property Detail
    property_id = fields.Many2one('property.details', string='Property', domain=[
                                  ('stage', '=', 'sale')])
    price = fields.Monetary(related="property_id.price", string="Price")
    type = fields.Selection(related="property_id.type", store=True)
    property_subtype_id = fields.Many2one(
        store=True, related="property_id.property_subtype_id")
    property_project_id = fields.Many2one(
        related="property_id.property_project_id", string="Project", store=True)
    subproject_id = fields.Many2one(
        related="property_id.subproject_id", string="Sub Project", store=True)
    total_area = fields.Float(related="property_id.total_area")
    usable_area = fields.Float(related="property_id.usable_area")
    measure_unit = fields.Selection(related="property_id.measure_unit")
    region_id = fields.Many2one(related="property_id.region_id")
    zip = fields.Char(related="property_id.zip")
    street = fields.Char(related="property_id.street", translate=True)
    street2 = fields.Char(related="property_id.street2", translate=True)
    city_id = fields.Many2one(related="property_id.city_id", string='City')
    country_id = fields.Many2one(
        related="property_id.country_id", string='Country')
    state_id = fields.Many2one(related="property_id.state_id")

    # Broker Details
    is_any_broker = fields.Boolean(string='Any Broker')
    broker_final_commission = fields.Monetary(
        string='Commission', compute="_compute_broker_final_commission")
    broker_commission = fields.Monetary(string='Commission ')
    commission_type = fields.Selection(
        [('f', 'Fix'), ('p', 'Percentage')], string="Commission Type")
    broker_commission_percentage = fields.Float(string='Percentage')
    commission_from = fields.Selection(
        [('customer', 'Customer'), ('landlord', 'Landlord',)], string="Commission From")
    broker_bill_id = fields.Many2one(
        'account.move', string='Broker Bill', readonly=True)
    broker_bill_payment_state = fields.Selection(
        related='broker_bill_id.payment_state', string="Payment Status ")
    broker_invoice_id = fields.Many2one(
        'account.move', string="Broker Invoice")
    broker_invoice_payment_state = fields.Selection(string="Broker Invoice Payment State",
                                                    related="broker_invoice_id.payment_state")

    # Customer Detail
    customer_id = fields.Many2one('res.partner', string='Customer', domain=[
                                  ('user_type', '=', 'customer')])
    customer_phone = fields.Char(string="Phone", related="customer_id.phone")
    customer_email = fields.Char(string="Email", related="customer_id.email")

    payment_term = fields.Selection([('monthly', 'Monthly'),
                                     ('full_payment', 'Full Payment'),
                                     ('quarterly', 'Quarterly')],
                                    string='Payment Term')
    sale_invoice_ids = fields.One2many(
        'sale.invoice', 'property_sold_id', string="Invoices")
    book_price = fields.Monetary(string='Book Price')
    sale_price = fields.Monetary(string='Confirmed Sale Price', store=True)
    ask_price = fields.Monetary(string='Customer Ask Price')
    book_invoice_id = fields.Many2one(
        'account.move', string='Advance', readonly=True)
    book_invoice_payment_state = fields.Selection(
        related='book_invoice_id.payment_state', string="Payment Status")
    book_invoice_state = fields.Boolean(string='Invoice State')
    remain_invoice_id = fields.Many2one('account.move', string="Invoice")
    remain_check = fields.Boolean(compute="_compute_remain_check")
    # Maintenance and utility Service
    is_any_maintenance = fields.Boolean(
        related="property_id.is_maintenance_service")
    total_maintenance = fields.Monetary(
        related="property_id.total_maintenance")
    is_utility_service = fields.Boolean(related="property_id.is_extra_service")
    total_service = fields.Monetary(related="property_id.extra_service_cost")
    # Total Amount Calculation
    total_sell_amount = fields.Monetary(
        string="Total Amount", compute="compute_sell_price")
    payable_amount = fields.Monetary(
        string="Installment Total Amount", compute="compute_sell_price")

    # Invoice Payment Calculation
    total_untaxed_amount = fields.Monetary(
        string="Untaxed Amount", compute="_compute_remain_amount")
    tax_amount = fields.Monetary(
        string="Tax Amount", compute="_compute_remain_amount")
    total_amount = fields.Monetary(
        string="Total Amount ", compute="_compute_remain_amount")
    remaining_amount = fields.Monetary(
        string="Remaining Amount", compute="_compute_remain_amount")
    paid_amount = fields.Monetary(
        string="Paid", compute="_compute_remain_amount")

    # Documents
    sold_document = fields.Binary(string='Sold Document')
    file_name = fields.Char('File Name', translate=True)

    # Terms & Conditions
    term_condition = fields.Html(string='Term and Condition')

    # Item & Taxes
    booking_item_id = fields.Many2one('product.product',
                                      string="Booking Item",
                                      default=lambda self: self.env.ref('cjg_finance_property.property_product_2',
                                                                        raise_if_not_found=False))
    broker_item_id = fields.Many2one('product.product',
                                     string="Broker Item",
                                     default=lambda self: self.env.ref('cjg_finance_property.property_product_3',
                                                                       raise_if_not_found=False))
    installment_item_id = fields.Many2one('product.product',
                                          string="Installment Item",
                                          default=lambda self: self.env.ref('cjg_finance_property.property_product_1',
                                                                            raise_if_not_found=False))
    is_taxes = fields.Boolean(string="Taxes ?")
    taxes_ids = fields.Many2many('account.tax', string="Taxes")

    maintenance_request_count = fields.Integer(string="Maintenance Request Count",
                                               compute="_compute_maintenance_request_count")

    # DEPRECATED START---------------------------------------------------
    sold_invoice_id = fields.Many2one('account.move',
                                      string='Sold Invoice',
                                      readonly=True)
    sold_invoice_state = fields.Boolean(string='Sold Invoice State')
    sold_invoice_payment_state = fields.Selection(related='sold_invoice_id.payment_state',
                                                  string="Payment Status  ")

    # --------------------------------------------------------DEPRECATED END

    # Create Write, Scheduler, Name-get
    # Create
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('sold_seq', _('New')) == _('New'):
                vals['sold_seq'] = self.env['ir.sequence'].next_by_code(
                    'property.vendor') or _('New')
        res = super(PropertyVendor, self).create(vals_list)
        return res

    # Default Get
    @api.model
    def default_get(self, fields_list):
        res = super(PropertyVendor, self).default_get(fields_list)
        default_installment_item = self.env['ir.config_parameter'].sudo().get_param(
            'cjg_finance_property.account_installment_item_id')
        res['installment_item_id'] = int(default_installment_item) if default_installment_item else self.env.ref(
            'cjg_finance_property.property_product_1').id
        return res

    # Name Get
    def name_get(self):
        data = []
        for rec in self:
            data.append((rec.id, '%s - %s' %
                         (rec.sold_seq, rec.customer_id.name)))
        return data

    # Scheduler
    @api.model
    def sale_recurring_invoice(self):
        reminder_days = self.env['ir.config_parameter'].sudo(
        ).get_param('cjg_finance_property.sale_reminder_days')
        today_date = fields.Date.today()
        # today_date = datetime.date(2023, 7, 29)
        sale_invoice = self.env['sale.invoice'].sudo().search(
            [('invoice_created', '=', False)])
        for data in sale_invoice:
            reminder_date = data.invoice_date - \
                relativedelta(days=int(reminder_days))
            invoice_post_type = self.env['ir.config_parameter'].sudo(
            ).get_param('cjg_finance_property.invoice_post_type')
            if today_date == reminder_date:
                record = {
                    'product_id': data.property_sold_id.installment_item_id.id,
                    'name': data.name + "\n" + (data.desc if data.desc else ""),
                    'quantity': 1,
                    'price_unit': data.amount,
                    'tax_ids': data.tax_ids.ids if data.tax_ids else False,
                }
                invoice_lines = [(0, 0, record)]
                sold_data = {
                    'partner_id': data.property_sold_id.customer_id.id,
                    'move_type': 'out_invoice',
                    'invoice_date': data.invoice_date,
                    'invoice_line_ids': invoice_lines
                }
                invoice_id = self.env['account.move'].sudo().create(sold_data)
                if invoice_post_type == 'automatically':
                    invoice_id.action_post()
                data.invoice_id = invoice_id.id
                data.invoice_created = True

    # Compute
    # Total amount paid amount, remaining amount
    @api.depends('sale_invoice_ids')
    def _compute_remain_amount(self):
        for rec in self:
            paid_amount = 0.0
            tax_amount = 0.0
            total_untaxed_amount = 0.0
            if rec.sale_invoice_ids:
                for data in rec.sale_invoice_ids:
                    total_untaxed_amount = total_untaxed_amount + data.amount
                    tax_amount = tax_amount + data.tax_amount
                    paid_amount = paid_amount + data.paid_amount
            rec.tax_amount = tax_amount
            rec.total_untaxed_amount = total_untaxed_amount
            rec.total_amount = tax_amount + total_untaxed_amount
            rec.paid_amount = paid_amount
            rec.remaining_amount = tax_amount + total_untaxed_amount - paid_amount

    # Remain Check
    @api.depends('sale_invoice_ids')
    def _compute_remain_check(self):
        for rec in self:
            if rec.sale_invoice_ids:
                for data in rec.sale_invoice_ids:
                    if data.is_remain_invoice:
                        rec.remain_check = True
                    else:
                        rec.remain_check = False
            else:
                rec.remain_check = False

    # Broker Commission
    @api.depends('is_any_broker', 'broker_id', 'commission_type', 'sale_price', 'broker_commission_percentage',
                 'sale_price', 'broker_commission')
    def _compute_broker_final_commission(self):
        for rec in self:
            if rec.is_any_broker:
                if rec.commission_type == 'p':
                    rec.broker_final_commission = rec.sale_price * \
                        rec.broker_commission_percentage / 100
                else:
                    rec.broker_final_commission = rec.broker_commission
            else:
                rec.broker_final_commission = 0.0

    # Count
    def _compute_maintenance_request_count(self):
        for rec in self:
            request_count = self.env['maintenance.request'].search_count(
                [('sell_contract_id', 'in', [rec.id])])
            rec.maintenance_request_count = request_count

    # Sell Price Calculation
    @api.depends('sale_price',
                 'book_price',
                 'total_service',
                 'is_utility_service',
                 'total_maintenance',
                 'is_any_maintenance')
    def compute_sell_price(self):
        for rec in self:
            tax_amount = 0.0
            total_sell_amount = 0.0
            if rec.is_any_maintenance:
                total_sell_amount = total_sell_amount + rec.total_maintenance
            if rec.is_utility_service:
                total_sell_amount = total_sell_amount + rec.total_service
            total_sell_amount = total_sell_amount + rec.sale_price
            rec.payable_amount = total_sell_amount + rec.book_price
            rec.tax_amount = tax_amount
            rec.total_sell_amount = total_sell_amount

    # Mail Template
    # Sold Mail
    def send_sold_mail(self):
        mail_template = self.env.ref(
            'cjg_finance_property.property_sold_mail_template')
        if mail_template:
            mail_template.send_mail(self.id, force_send=True)

    # Button
    # Advance Payment Invoice
    def action_book_invoice(self):
        mail_template = self.env.ref(
            'cjg_finance_property.property_book_mail_template')
        if mail_template:
            mail_template.send_mail(self.id, force_send=True)
        record = {
            'product_id': self.env.ref('cjg_finance_property.property_product_1').id,
            'name': 'Monto De Reserva ' + self.property_id.name,
            'quantity': 1,
            'price_unit': self.book_price
        }
        invoice_lines = [(0, 0, record)]
        data = {
            'partner_id': self.customer_id.id,
            'move_type': 'out_invoice',
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': invoice_lines
        }
        book_invoice_id = self.env['account.move'].sudo().create(data)
        book_invoice_id.sold_id = self.id
        invoice_post_type = self.env['ir.config_parameter'].sudo(
        ).get_param('cjg_finance_property.invoice_post_type')
        if invoice_post_type == 'automatically':
            book_invoice_id.action_post()
        self.book_invoice_id = book_invoice_id.id
        self.book_invoice_state = True
        self.property_id.stage = 'booked'
        self.stage = 'booked'
        return {
            'type': 'ir.actions.act_window',
            'name': 'Booked Invoice',
            'res_model': 'account.move',
            'res_id': book_invoice_id.id,
            'view_mode': 'form,tree',
            'target': 'current'
        }

    # Refund Amount
    def action_refund_amount(self):
        for rec in self:
            rec.stage = 'refund'
            rec.property_id.stage = "available"
            rec.property_id.sold_booking_id = None

    # Cancel Contract
    def action_cancel_contract(self):
        for rec in self:
            rec.stage = 'cancel'
            rec.property_id.stage = "available"
            rec.property_id.sold_booking_id = None

    # Lock Contract
    def action_locked_contract(self):
        for rec in self:
            rec.stage = 'locked'

    # Receive Remain Payment and Create Invoice
    def action_receive_remaining(self):
        amount = 0.0
        for rec in self.sale_invoice_ids:
            if not rec.invoice_created:
                amount = amount + rec.amount
        sold_invoice_data = {
            'name': "Remaining Invoice Payment",
            'property_sold_id': self.id,
            'invoice_date': fields.Date.today(),
            'amount': amount,
            'is_remain_invoice': True
        }
        self.env['sale.invoice'].create(sold_invoice_data)
        for data in self.sale_invoice_ids:
            if not data.invoice_created and (not data.is_remain_invoice):
                data.unlink()

    def action_reset_installments(self):
        """Reset Installments"""
        self.sale_invoice_ids = [(6, 0, 0)]

    # Confirm Sale
    def action_confirm_sale(self):
        """Confirm Sale and Update Status to SOLD"""
        if not self.sale_invoice_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'message': _("Please create installments to confirm sale."),
                    'sticky': False,
                }
            }
        self.write({
            "stage": "sold"
        })
        self.customer_id.write({
            "is_sold_customer": True
        })
        self.property_id.write({
            "stage": "sold"
        })
        # Send Confirmation Mail
        self.send_sold_mail()

    # Smart Button
    def action_maintenance_request(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Request',
            'res_model': 'maintenance.request',
            'domain': [('sell_contract_id', '=', self.id)],
            'context': {'create': False},
            'view_mode': 'kanban,tree,form',
            'target': 'current'
        }


class SaleInvoice(models.Model):
    _name = 'sale.invoice'
    _description = "Sale Invoice"

    name = fields.Char(string="Title", translate=True)
    property_sold_id = fields.Many2one('property.vendor',
                                       string="Property Sold",
                                       ondelete='cascade')
    invoice_id = fields.Many2one('account.move', string="Invoice")
    invoice_date = fields.Date(string="Date")
    payment_state = fields.Selection(related="invoice_id.payment_state")
    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency')
    amount = fields.Monetary(string="Amount")
    invoice_created = fields.Boolean()
    desc = fields.Text(string="Description", translate=True)
    is_remain_invoice = fields.Boolean()
    tax_ids = fields.Many2many('account.tax', string="Taxes")
    tax_amount = fields.Monetary(string="Tax Amount",
                                 compute="compute_tax_amount")

    total_amount = fields.Monetary(
        string="Total Amount", compute="_compute_amount")
    paid_amount = fields.Monetary(compute="_compute_amount")
    remaining_amount = fields.Monetary(compute="_compute_amount")

    @api.depends('tax_ids', 'amount', )
    def compute_tax_amount(self):
        for rec in self:
            total_tax = 0.0
            for data in rec.tax_ids:
                total_tax = total_tax + data.amount
            rec.tax_amount = rec.amount * total_tax / 100

    @api.depends("invoice_id")
    def _compute_amount(self):
        for rec in self:
            total_amount = 0.0
            remaining_amount = 0.0
            paid_amount = 0.0
            if rec.invoice_id:
                total_amount = rec.invoice_id.amount_total
                remaining_amount = rec.invoice_id.amount_residual
                paid_amount = rec.invoice_id.amount_total - rec.invoice_id.amount_residual 
            rec.total_amount = total_amount
            rec.remaining_amount = remaining_amount
            rec.paid_amount = paid_amount

    def action_create_invoice(self):
        invoice_post_type = self.env['ir.config_parameter'].sudo(
        ).get_param('cjg_finance_property.invoice_post_type')
        invoice_id = self.env['account.move'].sudo().create({
            'partner_id': self.property_sold_id.customer_id.id,
            'move_type': 'out_invoice',
            'sold_id': self.property_sold_id.id,
            'invoice_date': self.invoice_date,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.property_sold_id.installment_item_id.id,
                'name': self.name + "\n" + (self.desc if self.desc else ""),
                'quantity': 1,
                'price_unit': self.amount,
                'tax_ids': self.tax_ids.ids if self.tax_ids else False
            })]
        })
        if invoice_post_type == 'automatically':
            invoice_id.action_post()
        self.invoice_id = invoice_id.id
        self.invoice_created = True
        self.action_send_sale_invoice(invoice_id.id)

    def action_send_sale_invoice(self, invoice_id):
        mail_template = self.env.ref(
            'cjg_finance_property.sale_invoice_payment_mail_template')
        if mail_template:
            mail_template.send_mail(invoice_id, force_send=True)
