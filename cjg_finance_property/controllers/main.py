import logging
from odoo import fields, SUPERUSER_ID, api
from odoo.http import request, route
from odoo import http, tools, _
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError
from odoo.tools.mimetypes import guess_mimetype
import base64

_logger = logging.getLogger(__name__)


FILE_TYPE = ['image/jpeg', 'image/png', 'image/jpg']  # allowed file type

def get_encoded_image(image):
    if image:
        attachment = image.read()
        mimetype = guess_mimetype(base64.b64decode(base64.encodebytes(attachment)))
        if mimetype in FILE_TYPE:
            return base64.encodebytes(attachment)

# My Portal Sell and Rent Contract Count
class RentalCustomerPortal(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        sell_contract = request.env['property.vendor']
        domain = [('customer_id', '=', request.env.user.partner_id.id)]
        # Maintenance Count
        maintenance_count = request.env['maintenance.request'].sudo(
        ).search_count([])
        values['sell_contract_count'] = sell_contract.sudo().search_count(domain)
        values['maintenance_count'] = maintenance_count
        return values


# Controllers
class RentalPortalWebsite(http.Controller):
    # Tree view sale Contract
    @http.route(['/my/sell-contract/'], type='http', auth="user", website=True)
    def rental_user_sell_contract(self):
        customer_id = request.env.user.partner_id.id
        sell_contracts = request.env['property.vendor'].sudo().search(
            [('customer_id', '=', customer_id)])
        values = {'contract': sell_contracts}
        return request.render('cjg_finance_property.rental_user_sell_contract_info', values)

    # Form View Sale Contract
    @http.route(['/my/sell-contract/information/<model("property.vendor"):b>'], type='http', auth="user",
                website=True)
    def rental_user_sell_contract_detail(self, b):
        if b.customer_id.id == request.env.user.partner_id.id:
            values = {
                'sell_contract': b.sudo(),
            }
            return request.render('cjg_finance_property.rental_user_sell_contract_details', values)
        else:
            return request.redirect('/')

    # Tree View Rent Contract
    @http.route(['/my/rent-contract/'], type='http', auth="user", website=True)
    def rental_user_rent_contract(self):
        rent_contracts = request.env['tenancy.details'].sudo().search(
            [('tenancy_id', '=', request.env.user.partner_id.id)])
        return request.render('cjg_finance_property.rental_user_rent_contract_info',  {'contract': rent_contracts})

    # Form View Rent Contract
    @http.route(['/my/rent-contract/information/<model("tenancy.details"):rc>'], type='http', auth="user",
                website=True)
    def rental_user_rent_contract_detail(self, rc):
        maintenance_rec = request.env['product.template'].sudo().search(
            [('is_maintenance', '=', True)])
        if rc.tenancy_id.id == request.env.user.partner_id.id:
            values = {
                'rent': rc.sudo(),
                'maintenance_type': maintenance_rec
            }
            return request.render('cjg_finance_property.rental_user_rent_contract_details', values)
        else:
            return request.redirect('/')

    # Maintenance Request Creation
    @http.route(['/my/rent-contract/information/maintenance-request'], type='http', auth="user",
                website=True)
    def rental_rent_maintenance_request(self, **kw):
        tenancy_id = request.env['tenancy.details'].sudo().browse(
            int(kw.get('rent')))
        name = kw.get('request') if kw.get('request') else (
            str(tenancy_id.tenancy_seq) + " Maintenance Request")
        maintenance_type_id = int(kw.get('maintenance_type_id'))
        maintenance_rec = {
            'maintenance_type_id': maintenance_type_id if maintenance_type_id else False,
            'name': name,
            'property_id': tenancy_id.property_id.id,
            'tenancy_id': tenancy_id.id,
            'description': kw.get('desc')
        }
        maintenance_id = request.env['maintenance.request'].sudo().create(
            maintenance_rec)
        return request.redirect('/my/maintenance-request/')

    # Tree View of Maintenance request
    @http.route(['/my/maintenance-request/'], type='http', auth="user", website=True)
    def rental_user_maintenance_request(self):
        tenancies = request.env['tenancy.details'].sudo().search(
            [('tenancy_id', '=', request.env.user.partner_id.id)]).mapped('id')
        maintenance_requests = request.env['maintenance.request'].sudo().search(
            [('tenancy_id', 'in', tenancies)])
        return request.render('cjg_finance_property.rental_user_maintenance_info',  {'maintenance_rec': maintenance_requests})

    # From Maintenance Request
    @http.route(['/my/maintenance-request/information/<model("maintenance.request"):mr>'], type='http', auth="user", website=True)
    def rental_user_maintenance_request_details(self, mr):
        return request.render('cjg_finance_property.rental_user_maintenance_details', {'mr': mr.sudo()})


class PropertyImageController(http.Controller):

    @http.route(
        '/property/images/create', type='http', auth='user',
        methods=['POST'], csrf=True)
    def create_image(self, **kw):
        try:
            property_id = int(kw.get('property_id'))
        except (TypeError, ValueError):
            raise MissingError(_('La propiedad solicitada no existe.'))
        property_record = request.env['property.details'].sudo().browse(
            property_id).exists()
        if not property_record:
            raise MissingError(_('La propiedad solicitada no existe.'))
        if not property_record._portal_user_can_upload_image(request.env.user):
            raise AccessError(
                _('No tiene permiso para agregar imágenes a esta propiedad.'))
        if kw.get('images[]'):
            images = request.httprequest.files.getlist('images[]')
            if images:
                for image in images:
                    request.env['property.images'].sudo().create({
                            'title': image.filename.split('.')[0],
                            'property_id': property_record.id,
                            'image':  get_encoded_image(image),
                        })
        redirect_url = kw.get('url') or '/web'
        if not redirect_url.startswith('/'):
            redirect_url = '/web'
        return request.redirect(redirect_url)

    @http.route('/get/property/data', type='json', auth='public')
    def get_property_data(self, **kw):
        """Get property data for property list dashboard"""
        property_obj = request.env['property.details'].sudo()

        stages = ['available', 'booked', 'on_lease', 'sale', 'sold', 'draft']
        data = {}

        for stage in stages:
            data[f'{stage}_prop_count'] = property_obj.search_count([('stage', '=', stage)])
            data[f'{stage}_land_prop_count'] = property_obj.search_count([
                ('stage', '=', stage),
                ('type', '=', 'land'),
            ])
            data[f'{stage}_residential_prop_count'] = property_obj.search_count([
                ('stage', '=', stage),
                ('type', '=', 'residential'),
            ])
            data[f'{stage}_commercial_prop_count'] = property_obj.search_count([
                ('stage', '=', stage),
                ('type', '=', 'commercial'),
            ])
            data[f'{stage}_industrial_prop_count'] = property_obj.search_count([
                ('stage', '=', stage),
                ('type', '=', 'industrial'),
            ])

        data['total_prop_count'] = property_obj.search_count([('stage', '!=', 'draft')])
        data['total_land_prop_count'] = property_obj.search_count([
            ('stage', '!=', 'draft'),
            ('type', '=', 'land'),
        ])
        data['total_residential_prop_count'] = property_obj.search_count([
            ('stage', '!=', 'draft'),
            ('type', '=', 'residential'),
        ])
        data['total_commercial_prop_count'] = property_obj.search_count([
            ('stage', '!=', 'draft'),
            ('type', '=', 'commercial'),
        ])
        data['total_industrial_prop_count'] = property_obj.search_count([
            ('stage', '!=', 'draft'),
            ('type', '=', 'industrial'),
        ])

        return data
