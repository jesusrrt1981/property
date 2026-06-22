from odoo import models, api, fields, _


class BookingInquiry(models.TransientModel):
    _name = "booking.inquiry"
    _description = "Booking Inquiry"
    _rec_name = "customer_id"

    property_id = fields.Many2one('property.details', string="Property")
    customer_id = fields.Many2one('res.partner', string="Customer")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency')
    ask_price = fields.Monetary(string="Ask Price")
    note = fields.Text(string="Note", translate=True)
    sale_inquiry = fields.Boolean()
    sale_price = fields.Monetary(related="property_id.sale_price")

    def action_property_inquiry_booking(self):
        rec = self._context.get('active_id')
        lead_id = self.env['crm.lead'].browse(rec)
        if not self.property_id and not self.customer_id:
            message = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('Customer or property not Found !'),
                    'sticky': False,
                }
            }
            return message

        self.customer_id.user_type = "customer"
        if self.sale_inquiry:
            data = {
                'property_id': self.property_id.id,
                'customer_id': self.customer_id.id,
                'ask_price': self.ask_price,
                'note': self.note,
                'lead_id': lead_id.id
            }
            sale_inquiry_id = self.env['sale.inquiry'].create(data)
            lead_id.sale_inquiry_id = sale_inquiry_id.id
        else:
            data = {
                'property_id': self.property_id.id,
                'customer_id': self.customer_id.id,
                'note': self.note,
                'lead_id': lead_id.id
            }

