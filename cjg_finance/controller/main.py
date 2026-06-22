import logging

from odoo import http, tools, _, fields
from odoo.http import request
from odoo.addons.http_routing.models.ir_http import slug

_logger = logging.getLogger(__name__)


class SaleCreditManagement(http.Controller):
    @http.route('/salecredit/payment/preview/<url_token>', auth="public", type='http')
    def bank_cheque_preview(self, url_token, **kw):
        
        payment_id = request.env['sale.credit.payment'].sudo().search([('url_token', '=', url_token)], limit=1)
        if payment_id:
            values = {"docs": payment_id}
            return request.render("cjg_finance.report_credit_payment_ticket", values)
        else:
            return request.redirect('/')


class CajaController(http.Controller):
    pass
    
    @http.route('/cjg/caja/cheque_devuelto/create', type='json', auth='user')
    def returned_check_create(self, **kw):
        vals = {
            'partner_id': int(kw.get('partner_id')),
            'payment_id': int(kw.get('payment_id')) if kw.get('payment_id') else False,
            'date': kw.get('date'),
            'amount': float(kw.get('amount')),
            'reason': kw.get('reason'),
            'responsible_id': request.env.user.id,
        }
        rec = request.env['returned.check'].sudo().create(vals)
        return {'id': rec.id, 'name': rec.name}
