# -*- coding: utf-8 -*-
# Copyright 2023-Today TechKhedut.

import base64
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError
from odoo.addons.web_editor.tools import get_video_embed_code, get_video_thumbnail


class PropertySubProject(models.Model):
    _name = "property.sub.project"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Property Sub Project Details"

    # Sub Project Details
    name = fields.Char(string="Name", required=True, translate=True)
    project_sequence = fields.Char(string="Code", required=True)
    image_1920 = fields.Image(string="Image")
    property_project_id = fields.Many2one("property.project",
                                          string="Project")
    # Removed landlord from subproject
    project_for = fields.Selection(
        related="property_project_id.project_for", store=True)
    status = fields.Selection([("draft", "Draft"),
                               ("available", "Available"),
                               ("cancel", "Cancel"),
                               ("closed", "Closed")],
                              default="draft")
    property_type = fields.Selection(related="property_project_id.property_type", store=True,
                                     string="Property Type")
    property_subtype_id = fields.Many2one("property.sub.type", store=True,
                                          related="property_project_id.property_subtype_id",
                                          string="Property Subtype")

    # Company & Currency
    company_id = fields.Many2one("res.company",
                                 related="property_project_id.company_id",
                                 string="Company", required=True)
    currency_id = fields.Many2one("res.currency",
                                  related="property_project_id.currency_id",
                                  string="Currency")

    # Foreign currency and tax setup
    foreign_currency_id = fields.Many2one('res.currency', string='Foreign Currency')
    exchange_rate = fields.Float(string='Exchange Rate', help='Rate to convert foreign currency to company currency')
    sale_tax_ids = fields.Many2many('account.tax', string='Sale Taxes', domain="[('type_tax_use','=','sale')]")
    
    # Pricelist
    pricelist_id = fields.Many2one('product.pricelist', string='Lista de Precios', 
                                   help='Lista de precios aplicable a todas las unidades de este subproyecto')
    # Price Configuration (single)
    price_config_id = fields.Many2one(
        'subproject.price.config',
        string='Configuración de Precio',
        help='Configuración única de precio para el subproyecto. Todas las unidades pueden referenciarla.'
    )


    # Address
    region_id = fields.Many2one("property.region", string="Region", store=True,
                                related="property_project_id.region_id")
    street = fields.Char(string="Street",
                         translate=True)
    street2 = fields.Char(string="Street2")
    city_id = fields.Many2one('property.res.city',
                              string="City")
    state_id = fields.Many2one("res.country.state", string="State",
                               domain="[('country_id', '=?', country_id)]")
    zip = fields.Char(string="Zip", translate=True)
    country_id = fields.Many2one("res.country", string="Country")

    # Lat Long
    longitude = fields.Char(
        string='Longitude',
        related="property_project_id.longitude")
    latitude = fields.Char(
        string='Latitude',
        related="property_project_id.latitude")

    # Additional Details
    date_of_project = fields.Date(related="property_project_id.date_of_project",
                                  store=True,
                                  string="Date of Project")
    property_brochure = fields.Binary(string="Brochure")
    brochure_name = fields.Char(string="Brochure Name")
    construction_year = fields.Char(string="Construction Year",
                                    related="property_project_id.construction_year")
    website = fields.Char(string='Website')

    # Documents
    document_ids = fields.One2many("subproject.document", "subproject_id")

    # Availability
    avail_description = fields.Boolean(string="Descriptions")
    avail_amenity = fields.Boolean(string="Amenities")
    avail_specification = fields.Boolean(string="Specifications")
    avail_image = fields.Boolean(string="Images")

    project_image_ids = fields.One2many(
        related="property_project_id.project_image_ids",
        string="Images",
        readonly=True,
    )

    # Property Units
    property_unit_ids = fields.One2many("property.details", "subproject_id")
    floor_created = fields.Integer()

    # Basic Details
    sale_lease = fields.Selection([("rent", "Rent"),
                                   ("sale", "Sale")],
                                  string="Sale Lease", default="rent")
    total_floors = fields.Integer(string="Total Floors")
    units_per_floor = fields.Integer(string="Units per Floor")
    total_area = fields.Float(string="Total Property Area",
                              compute="compute_properties_statics")
    available_area = fields.Float(string="Available Area",
                                  compute="compute_properties_statics")
    total_values = fields.Monetary(string="Total Value of Project",
                                   compute="compute_properties_statics")
    total_maintenance = fields.Monetary(string="Total Maintenance",
                                        compute="compute_properties_statics")
    total_collection = fields.Monetary(string="Total Collection",
                                       compute="compute_properties_statics")
    scope_of_collection = fields.Monetary(string="Scope of Collection",
                                          compute="compute_properties_statics")

    # Description
    description = fields.Html(string="Description")

    # Amenities
    subproject_amenity_ids = fields.Many2many("property.amenities")

    # Specifications
    subproject_specification_ids = fields.Many2many("property.specification")

    # Images (eliminado: gestión de imágenes a nivel de subproyecto)


    # Count
    document_count = fields.Integer(compute="compute_count")
    unit_count = fields.Integer(compute="compute_count")
    available_unit_count = fields.Integer(compute="compute_count")
    sold_count = fields.Integer(compute="compute_count")
    rent_count = fields.Integer(compute="compute_count")

    # Unlink
    def unlink(self):
        for rec in self:
            # Only allow deletion in draft and without related records
            if rec.status != 'draft':
                raise ValidationError(
                    _("You can't delete subproject unless status is 'Draft'"))
            if rec.document_ids:
                raise ValidationError(
                    _("Cannot delete subproject while it has related documents"))
            if rec.property_unit_ids:
                raise ValidationError(
                    _("Cannot delete subproject, please delete corresponding units before deletion"))
            else:
                return super(PropertySubProject, self).unlink()

    # Compute
    # Count
    def compute_count(self):
        for rec in self:
            rec.document_count = self.env["subproject.document"].search_count(
                [("subproject_id", "=", rec.id)])
            rec.unit_count = self.env['property.details'].search_count(
                [('subproject_id', '=', rec.id)])
            rec.available_unit_count = self.env['property.details'].search_count(
                [('subproject_id', '=', rec.id), ('stage', '=', 'available')])
            rec.sold_count = self.env['property.details'].search_count(
                [('subproject_id', '=', rec.id), ('stage', 'in', ['sale', 'sold'])])
            rec.rent_count = self.env['property.details'].search_count(
                [('subproject_id', '=', rec.id), ('stage', '=', 'on_lease')])

    # Valuation Calculation
    @api.depends('sale_lease')
    def compute_properties_statics(self):
        for rec in self:
            total_area = 0.0
            available_area = 0.0
            total_values = 0.0
            total_maintenance = 0.0
            total_collection = 0.0
            scope_of_collection = 0.0
            properties = self.env['property.details'].sudo()
            project_domain = [('subproject_id', '=', rec.id)]
            properties_ids = self.env['property.details'].sudo().search(
                project_domain).mapped('id')
            properties_sale = self.env['property.vendor'].sudo().search(
                [('property_id', 'in', properties_ids)])
            if rec.sale_lease == 'sale':
                sale_domain = project_domain + \
                              [('sale_lease', '=', 'for_sale')]
                total_area = sum(properties.search(
                    sale_domain).mapped('total_area'))
                available_area = sum(properties.search(
                    sale_domain + [('stage', '=', 'available')]).mapped('total_area'))
                total_values = sum(properties.search(
                    sale_domain).mapped('price'))
                total_maintenance = sum(properties.search(
                    sale_domain + [('is_maintenance_service', '=', True)]).mapped('total_maintenance'))
                total_collection = sum(properties_sale.mapped('paid_amount'))
                scope_of_collection = sum(
                    properties_sale.mapped('remaining_amount'))
            rec.total_area = total_area
            rec.available_area = available_area
            rec.total_values = total_values
            rec.total_maintenance = total_maintenance
            rec.total_collection = total_collection
            rec.scope_of_collection = scope_of_collection

    # Onchange
    # Property Project info
    @api.onchange("property_project_id")
    def _onchange_property_project_id(self):
        self.street = self.property_project_id.street
        self.street2 = self.property_project_id.street2
        self.city_id = self.property_project_id.city_id.id
        self.state_id = self.property_project_id.state_id
        self.zip = self.property_project_id.zip
        self.country_id = self.property_project_id.country_id
        self.total_floors = self.property_project_id.total_floors
        self.total_area = self.property_project_id.total_area
        self.available_area = self.property_project_id.available_area
        self.property_brochure = self.property_project_id.property_brochure
        self.brochure_name = self.property_project_id.brochure_name

    @api.onchange('country_id')
    def _onchange_country_id(self):
        if self.country_id and self.country_id != self.state_id.country_id:
            self.state_id = False

    @api.onchange('state_id')
    def _onchange_state(self):
        if self.state_id.country_id:
            self.country_id = self.state_id.country_id

    # Property Sub Type Domain
    @api.onchange('property_type')
    def onchange_property_sub_type(self):
        for rec in self:
            rec.property_subtype_id = False

    # Action Button
    # Smart Button
    def action_document_count(self):
        return {
            "name": "Documents",
            "type": "ir.actions.act_window",
            "view_mode": "kanban,tree,form",
            "context": {'default_subproject_id': self.id},
            "domain": [("subproject_id", "=", self.id)],
            "res_model": "subproject.document",
            "target": "current",
        }

    def action_view_unit(self):
        return {
            "name": "Units",
            "type": "ir.actions.act_window",
            "domain": [("subproject_id", "=", self.id)],
            "view_mode": "tree,form",
            'context': {'create': False},
            "res_model": "property.details",
            "target": "current",
        }

    def action_view_available_unit(self):
        return {
            "name": "Available Units",
            "type": "ir.actions.act_window",
            "domain": [("subproject_id", "=", self.id), ('stage', '=', 'available')],
            "view_mode": "tree,form",
            'context': {'create': False},
            "res_model": "property.details",
            "target": "current",
        }

    def action_view_sold_unit(self):
        return {
            "name": "Sold / Sale Units",
            "type": "ir.actions.act_window",
            "domain": [("subproject_id", "=", self.id), ('stage', 'in', ['sold', 'sale'])],
            "view_mode": "tree,form",
            'context': {'create': False},
            "res_model": "property.details",
            "target": "current",
        }

    # G-map Location
    def action_gmap_location(self):
        if self.longitude and self.latitude:
            longitude = self.longitude
            latitude = self.latitude
            http_url = 'https://maps.google.com/maps?q=loc:' + latitude + ',' + longitude
            return {
                'type': 'ir.actions.act_url',
                'target': 'new',
                'url': http_url,
            }
        else:
            raise ValidationError(
                "! Enter Proper Longitude and Latitude Values")

    # Status
    def action_status_draft(self):
        self.status = 'draft'

    def action_status_available(self):
        self.status = 'available'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            try:
                if (not vals.get('exchange_rate') or vals.get('exchange_rate') == 0.0) and vals.get('foreign_currency_id'):
                    company = self.env['res.company'].browse(vals.get('company_id')) if vals.get('company_id') else self.env.company
                    company_currency = company.currency_id
                    foreign_currency = self.env['res.currency'].browse(vals['foreign_currency_id'])
                    conv = company_currency._convert(1.0, foreign_currency, company, fields.Date.context_today(self))
                    vals['exchange_rate'] = (1.0 / conv) if conv else 0.0
            except Exception:
                pass
        return super(PropertySubProject, self).create(vals_list)

    @api.onchange('foreign_currency_id')
    def _onchange_foreign_currency_id(self):
        if self.foreign_currency_id and (not self.exchange_rate or self.exchange_rate == 0.0):
            company = self.company_id or self.env.company
            company_currency = company.currency_id
            conv = company_currency._convert(1.0, self.foreign_currency_id, company, fields.Date.context_today(self))
            self.exchange_rate = (1.0 / conv) if conv else 0.0

    def action_update_unit_prices(self):
        """Actualizar precios de unidades no vendidas según la configuración de precio del subproyecto."""
        self.ensure_one()
        updated = 0
        units = self.property_unit_ids.filtered(lambda u: u.stage not in ['sale', 'sold'])
        for unit in units:
            if self.price_config_id:
                unit.write({'price': self.price_config_id.price, 'subproject_price_config_id': self.price_config_id.id})
                updated += 1
            elif self.pricelist_id and unit.product_id:
                # Fallback a lista de precios del subproyecto si no hay configuración específica
                try:
                    price = self.pricelist_id._get_product_price(unit.product_id, 1.0, False)
                except Exception:
                    price = unit.product_id.list_price
                unit.write({'price': price, 'subproject_price_config_id': False})
                updated += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Actualización de precios'),
                'message': _('Se actualizaron %s unidades no vendidas.') % updated,
                'type': 'success',
                'sticky': False,
            }
        }


# SubProject Document


class SubProjectDocument(models.Model):
    _name = "subproject.document"
    _description = "Documents for Sub Project"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(string="Name", required=True)
    document_name = fields.Char(string="Document Name")
    document_file = fields.Binary(string="Document", required=True)
    user_id = fields.Many2one("res.users", string="Added by", required=True)
    subproject_id = fields.Many2one('property.sub.project')


# Project Connectivity Line
class SubprojectConnectivityLine(models.Model):
    _name = 'subproject.connectivity.line'
    _description = "Sub Project Connectivity Line"

    subproject_id = fields.Many2one('property.sub.project')
    connectivity_id = fields.Many2one('property.connectivity',
                                      string="Nearby Connectivity")
    name = fields.Char(string="Name", translate=True)
    image = fields.Image(related="connectivity_id.image", string='Images')
    distance = fields.Char(string="Distance", translate=True)


# Property Images (eliminado: subproject.images.line)
