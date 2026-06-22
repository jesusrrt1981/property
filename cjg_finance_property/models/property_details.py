# -*- coding: utf-8 -*-
# Copyright 2025 CJG

import base64
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError, UserError
from odoo.addons.web_editor.tools import get_video_embed_code, get_video_thumbnail


class PropertyDetails(models.Model):
    _name = 'property.details'
    _description = 'Property Details and for registration new Property'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Property Details
    name = fields.Char(string='Name', required=True, translate=True)
    image = fields.Binary(string='Image')
    product_id = fields.Many2one('product.template', string='Product')
    categ_id = fields.Many2one('product.category', string='Product Category')
    type = fields.Selection([('land', 'Land'),
                             ], string='Property Type',
                            required=True,
                            default="land")
    
    # ==================================================================
    # Campos de CEMENTERIO (fieles a Testarossa: inventario_jardines)
    # PK física en Testarossa: jardin + fase + bloque + lote + osario
    # ==================================================================
    garden_id = fields.Many2one(
        'cemetery.garden', string='Jardín', index=True,
        help='id_jardin en Testarossa')
    phase_id = fields.Many2one(
        'cemetery.phase', string='Fase', help='id_fases en Testarossa')
    block = fields.Char(string='Bloque')
    lot = fields.Char(string='Lote')
    osuary_id = fields.Many2one(
        'cemetery.osuary',
        string='Osario',
        help='Osario dentro de la parcela (para restos cremados). Replica legacy sp_osarios.',
    )
    osario_code = fields.Char(
        string='Osario (legacy)', size=1,
        help='Campo legacy. Usar osuary_id para datos estructurados. Posición del osario dentro del bloque (A-E). Campo `osario` en Testarossa.'
    )
    is_ossuary = fields.Boolean(string='Es Osario')

    # CABIDA = capacidad física de la parcela (Testarossa: cavidades / osarios)
    cavities_capacity = fields.Integer(
        string='Cavidades (Cabida)', default=2,
        help='Cantidad de cuerpos que caben en la parcela. Campo `cavidades` en Testarossa.')
    ossuary_capacity = fields.Integer(
        string='Osarios', default=0,
        help='Cantidad de osarios/restos que caben. Campo `osarios` en Testarossa.')
    burial_count = fields.Integer(
        string='Inhumados', default=0,
        help='Cantidad de inhumaciones realizadas en esta parcela.')
    available_capacity = fields.Integer(
        string='Cabida Disponible', compute='_compute_available_capacity',
        store=True, help='Cavidades menos inhumados.')

    @api.depends('cavities_capacity', 'burial_count')
    def _compute_available_capacity(self):
        for rec in self:
            rec.available_capacity = (rec.cavities_capacity or 0) - (rec.burial_count or 0)
    
    sale_lease = fields.Selection([('for_sale', 'Sale')],
                                  string='Property For',
                                  default='for_sale',
                                  required=True)
    property_seq = fields.Char(string='Property Code',
                               required=True,
                               readonly=False,
                               copy=False,
                               default=lambda self: '')
    stage = fields.Selection([('draft', 'Draft'),
                              ('available', 'Available'),
                              ('booked', 'In Booking'),
                              ('sale', 'In Sale'),
                              ('sold', 'Sold'),
                              ('occupied', 'Con Inhumado')],
                             group_expand='_expand_groups',
                             string='Status',
                             default='draft',
                             copy=False,
                             required=True)
    
    
    # Funeral Occupation Tracking
    # burial_count = fields.Integer(
    #     string='Inhumados',
    #     compute='_compute_burial_count',
    #     store=True,
    #     help='Número de personas inhumadas en esta parcela'
    # )
    
    # max_burial_capacity = fields.Integer(
    #     string='Capacidad Máxima',
    #     default=1,
    #     help='Capacidad máxima de inhumados permitida'
    # )
    
    # is_occupied = fields.Boolean(
    #     string='Ocupada',
    #     compute='_compute_is_occupied',
    #     store=True,
    #     help='Verdadero si la parcela tiene al menos un inhumado'
    # )
    
    # burial_ids = fields.One2many(
    #     'funeral.burial',
    #     'property_id',
    #     string='Historial de Inhumaciones'
    # )



    # Campo computado para disponibilidad de crédito
    is_available_for_credit = fields.Boolean(
        string='Disponible para Crédito',
        compute='_compute_is_available_for_credit',
        store=True,
        help='Verdadero cuando el estado es Available o Sale'
    )

    # Multi Companies
    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency')

    # Property Sub Type
    property_subtype_id = fields.Many2one('property.sub.type',
                                          string="Property Sub Type",
                                          domain="[('type','=',type)]")

    # Project & Sub Project & Region
    region_id = fields.Many2one('property.region', string="Region")
    property_project_id = fields.Many2one('property.project',
                                          string="Project")
    subproject_id = fields.Many2one('property.sub.project',
                                    string="Sub Project")

    owners_ids = fields.Many2many('res.partner', string='Owners')

    # Address
    region_id = fields.Many2one('property.region', string="Region")
    zip = fields.Char(string='Zip')
    street = fields.Char(string='Street1', translate=True)
    street2 = fields.Char(string='Street2', translate=True)
    city = fields.Char(string='City  ', translate=True)
    city_id = fields.Many2one('property.res.city', string='City')
    country_id = fields.Many2one('res.country', 'Country')
    state_id = fields.Many2one(
        "res.country.state", string='State', store=True,
        domain="[('country_id', '=?', country_id)]")

    # Lat Long
    longitude = fields.Char(string='Longitude')
    latitude = fields.Char(string='Latitude')

    # Owner Details
    website = fields.Char(string='Website', translate=True)

    # Property Tags
    tag_ids = fields.Many2many('property.tag', string='Tags')

    # Availability
    amenities = fields.Boolean(string="Amenities")
    is_facilities = fields.Boolean(string="Specifications")
    is_images = fields.Boolean(string="Images")
    is_floor_plan = fields.Boolean(string="Floor Plans")
    nearby_connectivity = fields.Boolean(string="Nearby Connectivities")

    # Area Measurement
    is_section_measurement = fields.Boolean(
        string="Is Section Area Measurement")
    measure_unit = fields.Selection([('sq_ft', 'ft²'),
                                     ('sq_m', 'm²'),
                                     ('sq_yd', 'yd²'),
                                     ('cu_ft', 'ft³'),
                                     ('cu_m', 'm³')],
                                    default='sq_ft',
                                    string="Area Measurement Unit")
    room_measurement_ids = fields.One2many('property.room.measurement',
                                           'room_measurement_id',
                                           string='Area Measurement')
    total_room_measure = fields.Integer(compute='compute_room_measure',
                                        store=True)
    total_area = fields.Float(string="Total Area")
    usable_area = fields.Float(string="Usable Area")
    sq_ft = fields.Float(string="Total Ft²")
    sq_m = fields.Float(string="Total M²")
    sq_yd = fields.Float(string="Total Yd²")
    cu_ft = fields.Float(string="Total Ft³")
    cu_m = fields.Float(string="Total M³")

    # Pricing
    price = fields.Monetary(string="Price", currency_field='currency_id')

    # Foreign currency and tax setup
    foreign_currency_id = fields.Many2one('res.currency', string='Foreign Currency')
    exchange_rate = fields.Float(string='Exchange Rate', help='Rate to convert foreign currency to company currency (company_amount = foreign_amount * exchange_rate)')
    price_foreign = fields.Monetary(string='Foreign Price', currency_field='foreign_currency_id', compute='_compute_price_foreign', inverse='_inverse_price_foreign', store=True)
    sale_tax_ids = fields.Many2many('account.tax', string='Sale Taxes', domain="[('type_tax_use','=','sale')]")
    
    # Pricelist
    pricelist_id = fields.Many2one('product.pricelist', string='Lista de Precios', 
                                   help='Lista de precios específica para esta unidad. Si no se especifica, se usará la del subproyecto')
    subproject_price_config_id = fields.Many2one('subproject.price.config', string='Configuración de precio aplicada', readonly=False)
    max_qty = fields.Integer(string='Cantidad máxima vendible', default=1,
                              help='Copiado de la configuración de precio del subproyecto.')
    project_property_id = fields.Many2one(
        'property.sub.project',
        related='subproject_id',  # El campo ya existe directamente
        store=True,
        string='Proyecto'
    )
    adicional_ids = fields.Many2many(
        "product.template", 
        string="Adicionales",
        relation="product_template_land_rel",
        column1="land_id",
        column2="product_id",
        domain="[('adicional_project_ok', '=', True), '|', "
            "('project_property_id', '=', subproject_id), "  # Comparar con el proyecto correcto
            "('project_property_id', '=', False)]"
    )
    @api.depends('sale_price', 'price', 'exchange_rate', 'foreign_currency_id', 'company_id', 'subproject_id', 'property_project_id')
    def _compute_price_foreign(self):
        for rec in self:
            # Prefer unit local price over sale_price when present
            amount_company = rec.price or rec.sale_price or 0.0
            rate = rec.exchange_rate or 0.0
            # Fallback currency: subproject -> project -> current
            foreign_currency = rec.foreign_currency_id or getattr(rec.subproject_id, 'foreign_currency_id', False) or getattr(rec.property_project_id, 'foreign_currency_id', False)
            if foreign_currency and not rec.foreign_currency_id:
                rec.foreign_currency_id = foreign_currency
            if amount_company and foreign_currency:
                if rate and rate > 0:
                    # company_amount = foreign_amount * rate => foreign_amount = company_amount / rate
                    rec.price_foreign = amount_company / rate
                else:
                    # Fallback to Odoo currency conversion using company rates
                    try:
                        company_currency = rec.company_id.currency_id
                        rec.price_foreign = company_currency._convert(amount_company, foreign_currency, rec.company_id, fields.Date.today())
                    except Exception:
                        rec.price_foreign = 0.0
            else:
                rec.price_foreign = 0.0

    def _inverse_price_foreign(self):
        for rec in self:
            foreign_amount = rec.price_foreign or 0.0
            if not foreign_amount:
                # If cleared, do not force local price; leave as-is
                continue
            company = rec.company_id or self.env.company
            company_currency = company.currency_id
            foreign_currency = rec.foreign_currency_id or getattr(rec.subproject_id, 'foreign_currency_id', False) or getattr(rec.property_project_id, 'foreign_currency_id', False)
            local_amount = 0.0
            if rec.exchange_rate and rec.exchange_rate > 0:
                # company_amount = foreign_amount * rate
                local_amount = foreign_amount * rec.exchange_rate
            elif foreign_currency:
                # Fallback to conversion using currency rates
                try:
                    local_amount = foreign_currency._convert(foreign_amount, company_currency, company, fields.Date.context_today(self))
                except Exception:
                    local_amount = 0.0
            # Update primary price field
            rec.price = local_amount

    
    pricing_type = fields.Selection([('fixed', 'Fixed'),
                                     ('area_wise', 'Area Wise')],
                                    string="Pricing Type",
                                    default='fixed')
    price_per_area = fields.Monetary(string="Price / Area")

    # Utility Service
    is_extra_service = fields.Boolean(string="Utility Services")
    extra_service_ids = fields.One2many('extra.service.line',
                                        'property_id',
                                        string="Services")
    extra_service_cost = fields.Monetary(string="Utility Cost",
                                         compute="_compute_extra_service_cost")

    # Maintenance Service
    is_maintenance_service = fields.Boolean(string="Is Any Maintenance")
    maintenance_rent_type = fields.Selection([('once', 'Once'),
                                              ('recurring', 'Recurring')],
                                             string="Maintenance Type",
                                             default="once")
    maintenance_type = fields.Selection([('fixed', 'Fixed'),
                                         ('area_wise', 'Area Wise')],
                                        string="Charges Type")
    per_area_maintenance = fields.Monetary(string="Maintenance / Area")
    total_maintenance = fields.Monetary(string="Total Maintenance")

    #  Property Documents
    document_ids = fields.One2many('property.documents',
                                   'property_id',
                                   string="Documents")

    # Property Amities
    amenities_ids = fields.Many2many('property.amenities',
                                     string="Property Amenities")

    # Property Specification
    property_specification_ids = fields.Many2many('property.specification',
                                                  string='Property Specifications')

    # Image
    property_images_ids = fields.One2many('property.images',
                                          'property_id',
                                          string='Property Images')
    # Floor Plan
    floreplan_ids = fields.One2many('floor.plan',
                                    'property_id',
                                    string='Property Floor Plans')

    # Maintenance History
    maintenance_ids = fields.One2many('maintenance.request',
                                      'property_id',
                                      string='Maintenance Histories')

    # Increment History
    increment_history_ids = fields.One2many('increment.history', 'property_id')


    sold_booking_id = fields.Many2one('property.vendor', copy=False,
                                      string="Booking")
    sale_broker_count = fields.Integer(string="Sale Broker Count",
                                       compute="compute_count")

    #  Enquiry
    sale_inquiry_ids = fields.One2many('sale.inquiry',
                                       'property_id',
                                       string="Sale Enquiry")

    # CRM Lead
    lead_count = fields.Integer(string="Lead Count",
                                compute="_compute_lead")
    lead_opp_count = fields.Integer(string="Opportunity Count",
                                    compute="_compute_lead")

    # Property Type wise Details
    total_floor = fields.Integer(string='No of Floors')
    floor = fields.Integer(string='Floor')
    bed = fields.Integer(string='Rooms', default=1)
    bathroom = fields.Integer(string='Bathrooms', default=1)
    parking = fields.Integer(string='Parking', default=1)
    facing = fields.Selection([('N', 'North(N)'),
                               ('E', 'East(E)'),
                               ('S', 'South(S)'),
                               ('W', 'West(W)'),
                               ('NE', 'North-East(NE)'),
                               ('SE', 'South-East(SE)'),
                               ('SW', 'South-West(SW)'),
                               ('NW', 'North-West(NW)'), ],
                              string='Facing', default='N')
    furnishing_id = fields.Many2one('property.furnishing', string="Furnishing")
    unit_type = fields.Integer(string="Unit Type", default=1)

    # Smart Button Count
    document_count = fields.Integer(string='Document Count',
                                    compute='_compute_document_count')
    request_count = fields.Integer(string='Request Count',
                                   compute='_compute_request_count')
    booking_count = fields.Monetary(string='Booking Count',
                                    compute='_compute_booking_count')

    increment_history_count = fields.Integer(
        string="Increment History Count", compute="_compute_booking_count")
    vendor_count = fields.Integer(
        string="Sell Count", compute='_compute_booking_count')

    # Payment Plan Fields
    is_payment_plan = fields.Boolean(string='Has Payment Plan')
    payment_plan_id = fields.Many2one(
        'property.payment.plan',
        string='Payment Plan Template'
    )
    custom_payment_plan_line_ids = fields.One2many(
        'property.custom.payment.plan.line',
        'property_id',
        string='Custom Payment Plan'
    )
    payment_plan_total = fields.Float(
        string='Total Percentage',
        compute='_compute_payment_plan_total',
        store=True
    )
    # Additional Fees
    dld_fee_percentage = fields.Float(
        string='DLD Fee (%)',
        default=4.0,
        help='Dubai Land Department Fee percentage'
    )
    dld_fee_amount = fields.Monetary(
        string='DLD Fee Amount',
        compute='_compute_additional_fees',
        store=True
    )
    admin_fee = fields.Monetary(
        string='Admin Fee',
        default=2100.0,
        help='Administrative Fee'
    )
    total_with_fees = fields.Monetary(
        string='Total Amount (incl. Fees)',
        compute='_compute_additional_fees',
        store=True
    )

    # DEPRECATED START--------------------------------------------------------------------------------------------------
    # Pricing
    token_amount = fields.Monetary(string='Book Price')
    sale_price = fields.Monetary(string='Sale Price')
    # Property Details
    property_licence_no = fields.Char(string='License No.',
                                      translate=True)

    # Parent Property
    is_parent_property = fields.Boolean(string='Main Property')
    parent_property_id = fields.Many2one('parent.property')

    # Nearby Connectivity
    airport = fields.Char()
    national_highway = fields.Char()
    metro_station = fields.Char()
    metro_city = fields.Char()
    school = fields.Char()
    hospital = fields.Char()
    shopping_mall = fields.Char()
    park = fields.Char()
    # ---
    towers = fields.Boolean()
    no_of_towers = fields.Integer()
    facilities = fields.Text()
    # --
    parent_airport = fields.Char()
    parent_national_highway = fields.Char()
    parent_metro_station = fields.Char()
    parent_metro_city = fields.Char()
    parent_school = fields.Char()
    parent_hospital = fields.Char()
    parent_shopping_mall = fields.Char()
    parent_park = fields.Char()
    # --
    parent_zip = fields.Char()
    parent_street = fields.Char()
    parent_street2 = fields.Char()
    parent_city = fields.Char()
    parent_city_id = fields.Many2one(related='parent_property_id.city_id',
                                     string="Parent Cities")
    parent_country_id = fields.Many2one(related='parent_property_id.country_id',
                                        string="Parent Country")
    parent_state_id = fields.Many2one(related='parent_property_id.state_id',
                                      string="Parent State")
    parent_website = fields.Char()
    # --
    parent_amenities_ids = fields.Many2many(string="Parent Amentias",
                                            related='parent_property_id.amenities_ids')
    parent_specification_ids = fields.Many2many(string="Parent Specifications",
                                                related='parent_property_id.property_specification_ids')
    # Removed landlord reference from parent property
    # --
    construct_year = fields.Char(string="Construct Year",
                                 size=4)
    buying_year = fields.Char()
    address = fields.Char()
    sold_invoice_id = fields.Many2one('account.move')
    sold_invoice_state = fields.Boolean()
    certificate_ids = fields.One2many('property.certificate',
                                      'property_id',
                                      string='Certificates')
    
    room_no = fields.Char(string='Flat No./House No.')
    total_square_ft = fields.Char(string='Total Area Ft')
    usable_square_ft = fields.Char(string='Usable Area Ft')
    residence_type = fields.Selection([('apartment', 'Apartment'),
                                       ('bungalow', 'Bungalow'),
                                       ('vila', 'Vila'),
                                       ('raw_house', 'Raw House'),
                                       ('duplex', 'Duplex House'),
                                       ('single_studio', 'Single Studio')],
                                      string='Type of Residence')

    # Industrial
    industry_name = fields.Char()
    industry_location = fields.Selection([('inside', 'Inside City'),
                                          ('outside', 'Outside City')], )
    industrial_used_for = fields.Selection([('company', 'Company'),
                                            ('warehouses', 'Warehouses'),
                                            ('factories', 'Factories'),
                                            ('other', 'Other')])
    other_usages = fields.Char()
    industrial_facilities = fields.Text()
    # Land
    land_name = fields.Char()
    area_hector = fields.Char()
    land_facilities = fields.Text()
    # Commercial
    commercial_name = fields.Char()
    commercial_type = fields.Selection([('full_commercial', 'Full Commercial'),
                                        ('shops', 'Shops'),
                                        ('big_hall', 'Big Hall')])
    used_for = fields.Selection([('offices', 'Offices'),
                                 (' retail_stores', ' Retail Stores'),
                                 ('shopping_centres', 'Shopping Centres'),
                                 ('hotels', 'Hotels'),
                                 ('restaurants', 'Restaurants'),
                                 ('pubs', 'Pubs'),
                                 ('cafes', 'Cafes'),
                                 ('sport_facilities', 'Sport Facilities'),
                                 ('medical_centres', 'Medical Centres'),
                                 ('hospitals', 'Hospitals'),
                                 ('nursing_homes', 'Nursing Homes'),
                                 ('other', 'Other Use')
                                 ])
    floor_commercial = fields.Integer()
    total_floor_commercial = fields.Char()
    commercial_facilities = fields.Text()
    other_use = fields.Char()
    # Measurement
    commercial_measurement_ids = fields.One2many(
        'property.commercial.measurement', 'commercial_measurement_id')
    industrial_measurement_ids = fields.One2many(
        'property.industrial.measurement', 'industrial_measurement_id')
    total_commercial_measure = fields.Integer()
    total_industrial_measure = fields.Integer()
    furnishing = fields.Selection([('fully_furnished', 'Fully Furnished'),
                                   ('only_kitchen', 'Only Kitchen Furnished'),
                                   ('only_bed', 'Only BedRoom Furnished'),
                                   ('not_furnished', 'Not Furnished'),
                                   ], string='Furnishing Property', default='fully_furnished')
    credit_id = fields.Many2one(
        'sale.credit',
        string='Crédito Asociado',
        help='Crédito actualmente asociado a esta propiedad',
        ondelete='set null',
        index=True
    )
    
    # Campo computado opcional para saber si está en crédito
    is_in_credit = fields.Boolean(
        string='En Crédito',
        compute='_compute_is_in_credit',
        store=True,
        help='Indica si la propiedad está actualmente en un crédito activo'
    )
    
    @api.depends('credit_id', 'credit_id.state')
    def _compute_is_in_credit(self):
        """Determina si la propiedad está en un crédito activo"""
        for record in self:
            record.is_in_credit = bool(
                record.credit_id and 
                record.credit_id.state not in ('cancelled', 'refuse', 'desistido', 'closed')
            )
    
    @api.constrains('credit_id')
    def _check_credit_uniqueness(self):
        """Validar que una propiedad solo esté en un crédito activo a la vez"""
        for record in self:
            if record.credit_id:
                # Buscar otros créditos activos con esta propiedad
                other_credits = self.env['sale.credit'].search([
                    ('id', '!=', record.credit_id.id),
                    ('property_land_id', '=', record.id),
                    ('state', 'not in', ['cancelled', 'refuse', 'desistido', 'closed'])
                ])
                if other_credits:
                    raise ValidationError(
                        f'La propiedad {record.name} ya está asociada a otro crédito activo: '
                        f'{other_credits[0].name}'
                    )
    # ----------------------------------------------------------------------------------------------------DEPRECATED END

    # Create, Constrain, Write, Scheduler, Name get
    # Create
    @api.model_create_multi
    def create(self, vals_list):
        # Ensure exchange_rate is set to latest when 0 and foreign currency exists
        for vals in vals_list:
            try:
                fc_id = vals.get('foreign_currency_id')
                if not fc_id:
                    # Fallback: use subproject/project foreign currency if provided on creation
                    if vals.get('subproject_id'):
                        sp = self.env['property.sub.project'].browse(vals['subproject_id'])
                        fc_id = sp.foreign_currency_id.id if sp.foreign_currency_id else fc_id
                    if not fc_id and vals.get('property_project_id'):
                        pr = self.env['property.project'].browse(vals['property_project_id'])
                        fc_id = pr.foreign_currency_id.id if pr.foreign_currency_id else fc_id
                    if fc_id and not vals.get('foreign_currency_id'):
                        vals['foreign_currency_id'] = fc_id

                if fc_id and (not vals.get('exchange_rate') or vals.get('exchange_rate') == 0.0):
                    company = self.env['res.company'].browse(vals.get('company_id')) if vals.get('company_id') else self.env.company
                    company_currency = company.currency_id
                    foreign_currency = self.env['res.currency'].browse(fc_id)
                    conv = company_currency._convert(1.0, foreign_currency, company, fields.Date.context_today(self))
                    vals['exchange_rate'] = (1.0 / conv) if conv else 0.0
            except Exception:
                # Keep original value if conversion fails
                pass
        for vals in vals_list:
            if not vals.get('property_seq'):
                vals['property_seq'] = self.env['ir.sequence'].next_by_code(
                    'property.details') or ''
        res = super(PropertyDetails, self).create(vals_list)
        # Auto-crear producto por cada unidad creada
        for rec, vals in zip(res, vals_list):
            if not rec.product_id:
                image_bytes = vals.get('image') or (rec.property_images_ids and rec.property_images_ids[0].image)
                product_vals = {
                    'name': rec.name,
                    # Initialize product price from unit local price
                    'list_price': (rec.price or 0.0),
                }
                if image_bytes:
                    product_vals['image_1920'] = image_bytes
                categ_id = rec.property_project_id.categ_id.id if rec.property_project_id and rec.property_project_id.categ_id else False
                if categ_id:
                    product_vals['categ_id'] = categ_id
                product = self.env['product.template'].create(product_vals)
                rec.product_id = product.id
                # Ensure list_price stays in sync at creation time
                try:
                    product.list_price = rec.price or 0.0
                except Exception:
                    # Do not fail unit creation if product price sync fails
                    pass
                # Inicial: sincronizar impuestos de venta al producto
                try:
                    product.land_id = rec.id
                except Exception:
                    # Do not fail unit creation if product price sync fails
                    pass
                # Inicial: sincronizar impuestos de venta al producto
                if rec.sale_tax_ids:
                    product.taxes_id = [(6, 0, rec.sale_tax_ids.ids)]
        return res

    @api.onchange('foreign_currency_id')
    def _onchange_foreign_currency_id(self):
        if not self.foreign_currency_id:
            # Fallback to subproject/project currency if available
            self.foreign_currency_id = self.subproject_id.foreign_currency_id or self.property_project_id.foreign_currency_id
        if self.foreign_currency_id and (not self.exchange_rate or self.exchange_rate == 0.0):
            company = self.company_id or self.env.company
            company_currency = company.currency_id
            conv = company_currency._convert(1.0, self.foreign_currency_id, company, fields.Date.context_today(self))
            self.exchange_rate = (1.0 / conv) if conv else 0.0

    @api.onchange('price_foreign', 'exchange_rate', 'foreign_currency_id')
    def _onchange_price_foreign_sync_price(self):
        # Update local price immediately when the foreign price changes in the UI
        for rec in self:
            foreign_amount = rec.price_foreign or 0.0
            if not foreign_amount:
                continue
            company = rec.company_id or self.env.company
            company_currency = company.currency_id
            foreign_currency = rec.foreign_currency_id or getattr(rec.subproject_id, 'foreign_currency_id', False) or getattr(rec.property_project_id, 'foreign_currency_id', False)
            local_amount = 0.0
            if rec.exchange_rate and rec.exchange_rate > 0:
                local_amount = foreign_amount * rec.exchange_rate
            elif foreign_currency:
                try:
                    local_amount = foreign_currency._convert(foreign_amount, company_currency, company, fields.Date.context_today(self))
                except Exception:
                    local_amount = 0.0
            rec.price = local_amount

    # Stage Expand
    @api.model
    def _expand_groups(self, states, domain, order):
        return ['draft', 'available', 'booked', 'sale', 'sold']

    # Unlink
    def unlink(self):
        for rec in self:
            # Only allow deletion in Draft and without related records
            if rec.stage != 'draft':
                raise ValidationError(
                    _("You can't delete unit unless status is 'Draft'"))
            if rec.product_id:
                raise ValidationError(
                    _("Cannot delete unit while it has an associated product; please delete the product first"))
            if rec.document_ids:
                raise ValidationError(
                    _("Cannot delete unit while it has related documents"))
            return super(PropertyDetails, self).unlink()

    # Name-get
    def name_get(self):
        data = []
        for rec in self:
            if rec.is_parent_property:
                if rec.type == 'land':
                    data.append((rec.id, '%s - %s - Land' %
                                 (rec.name, rec.parent_property_id.name)))
                elif rec.type == 'residential':
                    data.append((rec.id, '%s - %s - Residential' %
                                 (rec.name, rec.parent_property_id.name)))
                elif rec.type == 'commercial':
                    data.append((rec.id, '%s - %s - Commercial' %
                                 (rec.name, rec.parent_property_id.name)))
                elif rec.type == 'industrial':
                    data.append((rec.id, '%s - %s - Industrial' %
                                 (rec.name, rec.parent_property_id.name)))
            else:
                if rec.type == 'land':
                    data.append((rec.id, '%s - Land' % rec.name))
                elif rec.type == 'residential':
                    data.append((rec.id, '%s - Residential' % rec.name))
                elif rec.type == 'commercial':
                    data.append((rec.id, '%s - Commercial' % rec.name))
                elif rec.type == 'industrial':
                    data.append((rec.id, '%s - Industrial' % rec.name))
        return data

    # Scheduler
    @api.model
    def update_property_address(self):
        properties = self.env['property.details'].search(
            [('is_parent_property', '=', True), ('parent_property_id', '!=', False)])
        for data in properties:
            data.onchange_parent_property_address()

    @api.model
    def update_property_measurement(self):
        """To Update measurement not required after vesrion 2.0"""
        pass

    @api.depends('room_measurement_ids', 'type', 'measure_unit', 'is_section_measurement')
    def compute_room_measure(self):
        for rec in self:
            total = 0
            if rec.room_measurement_ids:
                for data in rec.room_measurement_ids:
                    total = total + data.carpet_area
            rec.total_room_measure = total
            if rec.is_section_measurement:
                rec.total_area = total

    # CRM Leads
    @api.depends('sale_lease')
    def _compute_lead(self):
        for rec in self:
            rec.lead_count = self.env['crm.lead'].search_count(
                [('property_id', '=', rec.id), ('type', '=', 'lead')])
            rec.lead_opp_count = self.env['crm.lead'].search_count(
                [('property_id', '=', rec.id), ('type', '=', 'opportunity')])

    # Utility Service Total
    @api.depends('extra_service_ids')
    def _compute_extra_service_cost(self):
        for rec in self:
            amount = 0.0
            if rec.extra_service_ids:
                for data in rec.extra_service_ids:
                    amount = amount + data.price
            rec.extra_service_cost = amount

    @api.depends('stage')
    def _compute_is_available_for_credit(self):
        """Compute if property is available for credit based on stage"""
        for rec in self:
            rec.is_available_for_credit = rec.stage in ('available', 'sale')
    
    # @api.depends('burial_ids')
    # def _compute_burial_count(self):
    #     """Computa el número de inhumados en la parcela"""
    #     for rec in self:
    #         # rec.burial_count = len(rec.burial_ids.filtered(lambda b: b.state == 'buried'))
    #         pass
    
    # @api.depends('burial_count')
    # def _compute_is_occupied(self):
    #     """Determina si la parcela está ocupada"""
    #     for rec in self:
    #         # rec.is_occupied = rec.burial_count > 0
    #         # Auto-cambiar estado si tiene inhumados
    #         # if rec.is_occupied and rec.stage == 'sold':
    #         #     rec.stage = 'occupied'
    #         pass

    # Counts
    # Document Count
    def _compute_document_count(self):
        for rec in self:
            document_count = self.env['property.documents'].search_count(
                [('property_id', '=', rec.id)])
            rec.document_count = document_count

    # Booking Count
    def _compute_booking_count(self):
        for rec in self:
            count = self.sold_booking_id.book_price
            rec.booking_count = count
            rec.increment_history_count = self.env['increment.history'].search_count(
                [('property_id', '=', rec.id)])
            rec.vendor_count = self.env['property.vendor'].search_count(
                [('property_id', '=', rec.id)])

    # Maintenance Request Count
    def _compute_request_count(self):
        for rec in self:
            request_count = self.env['maintenance.request'].search_count(
                [('property_id', '=', rec.id)])
            rec.request_count = request_count

    # Count
    def compute_count(self):
        for rec in self:
            rec.sale_broker_count = len(self.env['property.vendor'].sudo(
            ).search([('property_id', '=', rec.id), ('is_any_broker', '=', True)]).mapped('broker_id').mapped('id'))

    # Payment Plan Compute Methods
    @api.depends('custom_payment_plan_line_ids.percentage')
    def _compute_payment_plan_total(self):
        for rec in self:
            total = sum(rec.custom_payment_plan_line_ids.mapped('percentage'))
            rec.payment_plan_total = total

    @api.depends('price', 'dld_fee_percentage', 'admin_fee')
    def _compute_additional_fees(self):
        for rec in self:
            rec.dld_fee_amount = (rec.price * rec.dld_fee_percentage) / 100.0
            rec.total_with_fees = rec.price + rec.dld_fee_amount + rec.admin_fee

    # Onchange
    # Area Wise Price
    @api.onchange('pricing_type', 'price_per_area', 'measure_unit', 'room_measurement_ids', 'is_section_measurement',
                  'total_area')
    def onchange_fix_area_price(self):
        for rec in self:
            if rec.pricing_type == 'area_wise':
                rec.price = rec.total_area * rec.price_per_area

    @api.onchange('subproject_id', 'product_id')
    def _onchange_price_from_subproject_pricelist(self):
        for rec in self:
            if rec.subproject_id:
                if rec.subproject_id.price_config_id:
                    rec.subproject_price_config_id = rec.subproject_id.price_config_id
                    rec.price = rec.subproject_id.price_config_id.price
                    rec.max_qty = rec.subproject_id.price_config_id.max_qty or 1
                else:
                    # Fallback a lista de precios del subproyecto o de la unidad
                    pricelist = rec.pricelist_id or rec.subproject_id.pricelist_id
                    if pricelist and rec.product_id:
                        try:
                            rec.price = pricelist._get_product_price(rec.product_id, 1.0, False)
                        except Exception:
                            rec.price = rec.product_id.list_price

    @api.onchange('subproject_price_config_id')
    def _onchange_subproject_price_config_id(self):
        for rec in self:
            if rec.subproject_price_config_id:
                rec.price = rec.subproject_price_config_id.price
                rec.max_qty = rec.subproject_price_config_id.max_qty or 1

    def write(self, vals):
        # Validar cambios de precio cuando hay contrato activo
        if 'price' in vals or 'price_foreign' in vals:
            for rec in self:
                # Verificar si tiene un contrato de venta activo
                if rec.sold_booking_id and rec.sold_booking_id.stage not in ('cancel', 'refund'):
                    raise ValidationError(_(
                        "No se puede cambiar el precio de la propiedad '%s' porque tiene un contrato "
                        "de venta activo (Contrato: %s). Por favor, cancele o reembolse el contrato primero."
                    ) % (rec.name, rec.sold_booking_id.sold_seq))
                
                # Verificar si tiene un crédito activo
                if rec.credit_id and rec.credit_id.state not in ('cancelled', 'refuse', 'desistido', 'closed'):
                    raise ValidationError(_(
                        "No se puede cambiar el precio de la propiedad '%s' porque está asociada a un "
                        "crédito activo (Crédito: %s, Estado: %s). No se permiten cambios de precio después "
                        "de la aprobación del crédito."
                    ) % (rec.name, rec.credit_id.name, rec.credit_id.state))
        
        res = super(PropertyDetails, self).write(vals)
        # Sync product sale price when unit price changes (explicit or via inverse of price_foreign)
        if 'price' in vals or 'price_foreign' in vals:
            for rec in self:
                if rec.product_id:
                    rec.product_id.with_context(from_property_details=True).write({
                        'list_price': rec.price or 0.0
                    })
        # Sync product foreign currency fields when unit fields change
        if 'foreign_currency_id' in vals or 'exchange_rate' in vals:
            for rec in self:
                if rec.product_id:
                    tmpl = rec.product_id
                    vals_to_write = {}
                    # Update foreign currency if provided
                    if 'foreign_currency_id' in vals:
                        vals_to_write['foreign_currency_id'] = rec.foreign_currency_id.id if rec.foreign_currency_id else False
                    # Update exchange rate if provided
                    if 'exchange_rate' in vals:
                        vals_to_write['exchange_rate'] = rec.exchange_rate or 0.0
                    if vals_to_write:
                        tmpl.with_context(from_property_details=True).write(vals_to_write)

                    # price_foreign on template is computed from list_price/exchange_rate/foreign_currency
                    # so we don't set it directly; it will recompute automatically
        # Sync product sale taxes when unit taxes change
        if 'sale_tax_ids' in vals:
            for rec in self:
                if rec.product_id:
                    rec.product_id.taxes_id = [(6, 0, rec.sale_tax_ids.ids)]
        # Sync product category when unit category changes
        if 'categ_id' in vals:
            for rec in self:
                if rec.product_id and rec.categ_id:
                    rec.product_id.categ_id = rec.categ_id.id
        return res

    # Maintenance Area wise Price
    @api.onchange('is_maintenance_service', 'maintenance_type', 'per_area_maintenance')
    def onchange_maintenance_type_charges(self):
        for rec in self:
            if rec.is_maintenance_service and rec.maintenance_type == 'area_wise':
                rec.total_maintenance = rec.per_area_maintenance * rec.total_area

    # Total Area
    @api.onchange('room_measurement_ids', 'is_section_measurement')
    def onchange_area_measure(self):
        for rec in self:
            total = 0.0
            if rec.is_section_measurement and rec.room_measurement_ids:
                for data in rec.room_measurement_ids:
                    total = total + data.carpet_area
                rec.total_area = total

    # Property Sub Type Domain
    @api.onchange('type')
    def onchange_property_sub_type(self):
        for rec in self:
            rec.property_subtype_id = False

    # State And Country Onchange
    @api.onchange('country_id')
    def _onchange_country_id(self):
        if self.country_id and self.country_id != self.state_id.country_id:
            self.state_id = False

    @api.onchange('state_id')
    def _onchange_state(self):
        if self.state_id.country_id:
            self.country_id = self.state_id.country_id

    # Buttons
    # Stage Buttons
    def action_in_available(self):
        for rec in self:
            rec.stage = 'available'

    def action_in_booked(self):
        for rec in self:
            rec.stage = 'booked'

    def action_sold(self):
        for rec in self:
            rec.stage = 'sold'

    def action_draft_property(self):
        self.stage = "draft"

    def action_open_cambiar_parcela_wizard(self):
        """Abre el wizard de Cambio de Parcela (Mejora de Parcela).

        Replica el flujo legacy de testarossa/modulos/contratos/class/class.Contratos.php::cambiarProducto
        que permite cambiar la parcela asignada a un contrato activo.
        """
        self.ensure_one()
        if self.stage not in ('sold', 'occupied'):
            raise UserError(_(
                "Solo se puede cambiar la parcela de una unidad en estado "
                "'Sold' u 'Occupied'. Estado actual: %s."
            ) % self.stage)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cambiar Parcela'),
            'res_model': 'cambiar.parcela.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'cjg_finance_property.view_cambiar_parcela_wizard_form'
            ).id,
            'target': 'new',
            'context': {
                'default_parcela_vieja_id': self.id,
            },
        }

    def action_liberar_parcela(self):
        """Libera la parcela (cambia a 'available') y limpia el booking.

        Útil para correcciones administrativas cuando se quiere desvincular
        una parcela de un contrato sin asignar una nueva (el contrato debe
        gestionarse por separado).
        """
        for rec in self:
            if rec.stage not in ('sold', 'occupied', 'booked'):
                raise UserError(_(
                    "Solo se pueden liberar parcelas en estado 'Sold', "
                    "'Occupied' o 'Booked'. Estado actual: %s."
                ) % rec.stage)
            booking = rec.sold_booking_id
            booking_name = booking.name if booking else 'N/A'
            rec.write({
                'stage': 'available',
                'sold_booking_id': False,
            })
            rec.message_post(body=_(
                "Parcela liberada manualmente. "
                "Contrato previo: %s. "
                "Motivo: Liberación administrativa desde el form de la parcela."
            ) % booking_name)
            if booking:
                booking.message_post(body=_(
                    "La parcela %s fue liberada desde la vista de parcela. "
                    "Este contrato ya no tiene parcela asignada. "
                    "Use el wizard 'Cambiar Parcela' para asignar una nueva "
                    "o gestione la liberación del contrato."
                ) % rec.display_name)

    def action_in_sale(self):
        if self.sale_lease == 'for_sale':
            self.stage = 'sale'
        else:
            message = {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'title': 'You need to set "Price/Rent" to "For Sale" to proceed',
                    'sticky': False,
                }
            }
            return message

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

    # Smart Button
    def action_maintenance_request(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Request',
            'res_model': 'maintenance.request',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id, 'create': False},
            'view_mode': 'kanban,tree,form',
            'target': 'current'
        }

    def action_property_document(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Document',
            'res_model': 'property.documents',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
            'view_mode': 'tree',
            'target': 'current'
        }

    def action_sale_booking(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Booking Information',
            'res_model': 'property.vendor',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
            'view_mode': 'tree,form',
            'target': 'current'
        }

    def action_crm_lead(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Leads',
            'res_model': 'crm.lead',
            'domain': [('property_id', '=', self.id), ('type', '=', 'lead')],
            'context': {'default_property_id': self.id, 'default_type': 'lead'},
            'view_mode': 'tree,form',
            'target': 'current'
        }

    def action_crm_lead_opp(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Opportunity',
            'res_model': 'crm.lead',
            'domain': [('property_id', '=', self.id), ('type', '=', 'opportunity')],
            'context': {'default_property_id': self.id, 'default_type': 'opportunity'},
            'view_mode': 'tree,form',
            'target': 'current'
        }

    def action_view_contract(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rent Contracts',
            'res_model': 'tenancy.details',
            'domain': [('property_id', '=', self.id)],
            'context': {'create': False},
            'view_mode': 'tree,form',
            'target': 'current'
        }

    def action_view_sell_contract(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sell Contracts',
            'res_model': 'property.vendor',
            'domain': [('property_id', '=', self.id)],
            'context': {'create': False},
            'view_mode': 'list,form',
            'target': 'current'
        }

    def action_property_sale_broker(self):
        ids = self.env['property.vendor'].sudo().search(
            [('property_id', '=', self.id), ('is_any_broker', '=', True)]).mapped('broker_id').mapped('id')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Brokers',
            'res_model': 'res.partner',
            'domain': [('id', 'in', ids)],
            'context': {'create': False},
            'view_mode': 'tree,form',
            'target': 'current'
        }

    def action_view_increment_history(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Increment History',
            'res_model': 'increment.history',
            'domain': [('property_id', '=', self.id)],
            'context': {'create': False},
            'view_mode': 'tree,form',
            'target': 'current'
        }

    # Server Action
    def action_available_property(self):
        active_ids = self._context.get('active_ids')
        property_rec = self.env['property.details'].sudo().browse(active_ids)
        for data in property_rec:
            if data.stage == 'draft':
                data.write({
                    'stage': 'available'
                })

    # DashBoard
    @api.model
    def get_property_stats(self):
        company_domain = [('company_id', 'in', self.env.companies.ids)]
        # Property Stages
        property = self.env['property.details']
        avail_property = property.sudo().search_count(
            [('stage', '=', 'available')] + company_domain)
        booked_property = property.sudo().search_count(
            [('stage', '=', 'booked')] + company_domain)
        sale_property = property.sudo().search_count(
            [('stage', '=', 'sale')] + company_domain)
        sold_property = property.sudo().search_count(
            [('stage', '=', 'sold')] + company_domain)
        currency_symbol = self.env.company.currency_id.symbol
        land_property = property.sudo().search_count(
            [('type', '=', 'land')] + company_domain)
        residential_property = property.sudo().search_count(
            [('type', '=', 'residential')] + company_domain)
        commercial_property = property.sudo().search_count(
            [('type', '=', 'commercial')] + company_domain)
        industrial_property = property.sudo().search_count(
            [('type', '=', 'industrial')] + company_domain)
        property_type = [['Land', 'Residential', 'Commercial', 'Industrial'],
                         [land_property, residential_property, commercial_property, industrial_property]]
        property_stage = [['Available Properties', 'Sold Properties', 'Booked Properties', 'On Sale'],
                          [avail_property, sold_property, booked_property, sale_property]]

        # Rent Contract

        # Sale Contract
        sale_contract = self.env['property.vendor'].sudo()
        booked = sale_contract.search_count(
            [('stage', '=', 'booked')] + company_domain)
        sale_sold = sale_contract.search_count(
            [('stage', '=', 'sold')] + company_domain)
        refund = sale_contract.search_count(
            [('stage', '=', 'refund')] + company_domain)
        sold_total = sum(sale_contract.search(
            [('stage', '=', 'sold')] + company_domain).mapped('sale_price'))
        pending_invoice_sale = self.env['account.move'].search_count(
            [('sold_property_id', '!=', False), ('payment_state', '=', 'not_paid')] + company_domain)

        # Region, Project, Sub Project, Properties
        region_count = self.env['property.region'].search_count([])
        project_count = self.env['property.project'].search_count(
            company_domain)
        subproject_count = self.env['property.sub.project'].search_count(
            company_domain)
        total_property = property.search_count(company_domain)

        # Customer & Landlord
        customer_count = self.env['res.partner'].sudo(
        ).search_count([('user_type', '=', 'customer')])
      
        return {
            # Property
            'avail_property': avail_property,
            'booked_property': booked_property,
            'sale_property': sale_property,
            'sold_property': sold_property,
            # Sale Contract
            'booked': booked,
            'sale_sold': sale_sold,
            'refund': refund,
            'sold_total': str(round(sold_total, 2)) + ' ' + currency_symbol if currency_symbol else "",
            'pending_invoice_sale': pending_invoice_sale,
            # Customer & Landlord
            'customer_count': customer_count,
            # Region, Project, Sub Project, Properties
            'region_count': region_count,
            'project_count': project_count,
            'subproject_count': subproject_count,
            'total_property': total_property,
            # Graph
            'property_type': property_type,
            'property_stage': property_stage,
            'property_map_data': self.get_property_map_data(),
            'due_paid_amount': self.due_paid_amount()
        }


    def due_paid_amount(self):
        company_domain = [('company_id', 'in', self.env.companies.ids)]
        sold = {}
        not_paid_amount_sold = 0.0
        paid_amount_sold = 0.0
        property_sold = self.env['account.move'].sudo().search([('sold_property_id', '!=', False)] + company_domain)
        for data in property_sold:
            if data.sold_property_id.stage == "sold":
                if data.payment_state == "not_paid":
                    not_paid_amount_sold = not_paid_amount_sold + data.amount_total
                if data.payment_state == "paid":
                    paid_amount_sold = paid_amount_sold + data.amount_total
        sold['Due'] = not_paid_amount_sold
        sold['Paid'] = paid_amount_sold

        return [list(sold.keys()), list(sold.values())]
    

    def get_property_map_data(self):
        company_domain = [('company_id', 'in', self.env.companies.ids)]
        data = []
        properties = self.env['property.details'].sudo().search(
            [('stage', '=', 'available')] + company_domain)
        for prop in properties:
            if not prop.latitude or not prop.longitude:
                continue
            title = "Property : " + prop.name + (
                ("\nRegion :" + prop.region_id.name) if prop.region_id.name else "") + (
                ("\nCity :" + prop.city_id.name) if prop.city_id.name else "")
            data.append({
                'title': title,
                'latitude': prop.latitude,
                'longitude': prop.longitude,
            })
        return data


# Area Measurement
class PropertyRoomMeasurement(models.Model):
    _name = 'property.room.measurement'
    _description = 'Room Property Measurement Details'

    type_room = fields.Selection([('hall', 'Hall'),
                                  ('bed_room', 'Bed Room'),
                                  ('kitchen', 'Kitchen'),
                                  ('drawing_room', 'Drawing Room'),
                                  ('bathroom', 'Bathroom'),
                                  ('store_room', 'Store Room'),
                                  ('balcony', 'Balcony'),
                                  ('wash_area', 'Wash Area'), ],
                                 string='House Section')
    section_id = fields.Many2one('property.area.type', string="Section")
    length = fields.Integer(string='Length')
    width = fields.Integer(string='Width')
    height = fields.Integer(string='Height', default=1)
    no_of_unit = fields.Integer(string="No of Unit", default=1)
    carpet_area = fields.Integer(string='Total Area',
                                 compute='_compute_carpet_area')
    measure = fields.Char(string='ft²',
                          default='ft²',
                          readonly=True,
                          translate=True)
    room_measurement_id = fields.Many2one('property.details',
                                          string='Room Details')
    measure_unit = fields.Selection(related="room_measurement_id.measure_unit",
                                    store=True)
    sq_ft = fields.Float(string="Total Square Feet")
    sq_m = fields.Float(string="Total Square Meters")
    sq_yd = fields.Float(string="Total Square Yards")
    cu_ft = fields.Float(string="Total Cubic Feet")
    cu_m = fields.Float(string="Total Cubic Meters")

    @api.depends('length', 'width', 'height', 'measure_unit', 'no_of_unit')
    def _compute_carpet_area(self):
        for rec in self:
            total = 0.0
            if rec.measure_unit in ['sq_ft', 'sq_m', 'sq_yd']:
                total = rec.length * rec.width * rec.no_of_unit
            elif rec.measure_unit in ['cu_ft', 'cu_m']:
                total = rec.length * rec.width * rec.height * rec.no_of_unit
            rec.carpet_area = total


# Property Documents
class PropertyDocuments(models.Model):
    _name = 'property.documents'
    _description = 'Document related to Property'
    _rec_name = 'doc_type'

    property_id = fields.Many2one('property.details',
                                  string='Property Name',
                                  readonly=True)
    document_date = fields.Date(string='Date', default=fields.Date.today())
    doc_type = fields.Selection([('photos', 'Photo'),
                                 ('brochure', 'Brochure'),
                                 ('certificate', 'Certificate'),
                                 ('insurance_certificate',
                                  'Insurance Certificate'),
                                 ('utilities_insurance', 'Utilities Certificate')],
                                string='Document Type', required=True)
    document = fields.Binary(string='Documents', required=True)
    file_name = fields.Char(string='File Name', translate=True)


# Property Amentias
class PropertyAmenities(models.Model):
    _name = 'property.amenities'
    _description = 'Details About Property Amenities'
    _rec_name = 'title'

    sequence = fields.Integer()
    image = fields.Binary(string='Image')
    title = fields.Char(string='Title', translate=True)

    def unlink(self):
        for rec in self:
            # Prevent deletion if referenced by properties or parent properties
            prop_count = self.env['property.details'].search_count([
                ('amenities_ids', 'in', rec.id)
            ])
            parent_count = self.env['parent.property'].search_count([
                ('amenities_ids', 'in', rec.id)
            ])
            project_count = self.env['property.project'].search_count([
                ('property_amenity_ids', 'in', rec.id)
            ])
            subproject_count = self.env['property.sub.project'].search_count([
                ('subproject_amenity_ids', 'in', rec.id)
            ])
            if prop_count or parent_count or project_count or subproject_count:
                raise ValidationError(
                    _("Cannot delete amenity because it is referenced by other records"))
        return super(PropertyAmenities, self).unlink()


# Property Specification
class PropertySpecification(models.Model):
    _name = 'property.specification'
    _description = 'Details About Property Specification'
    _rec_name = 'title'

    image = fields.Image(string='Image')
    title = fields.Char(string='Title', translate=True)
    description = fields.Text(string="Description", translate=True)
    description_line1 = fields.Char(string='Description ', translate=True)
    description_line2 = fields.Char(string='Description Line 2',
                                    translate=True)
    description_line3 = fields.Char(string='Description Line 3',
                                    translate=True)

    def unlink(self):
        for rec in self:
            # Prevent deletion if referenced by properties or parent properties
            prop_count = self.env['property.details'].search_count([
                ('property_specification_ids', 'in', rec.id)
            ])
            parent_count = self.env['parent.property'].search_count([
                ('property_specification_ids', 'in', rec.id)
            ])
            project_count = self.env['property.project'].search_count([
                ('property_specification_ids', 'in', rec.id)
            ])
            subproject_count = self.env['property.sub.project'].search_count([
                ('subproject_specification_ids', 'in', rec.id)
            ])
            if prop_count or parent_count or project_count or subproject_count:
                raise ValidationError(
                    _("Cannot delete specification because it is referenced by other records"))
        return super(PropertySpecification, self).unlink()


# Property Floor Plan
class FloorPlan(models.Model):
    _name = 'floor.plan'
    _description = 'Details About Floor Plan'
    _inherit = ["image.mixin"]
    _order = "sequence, id"

    title = fields.Char(string='Title', translate=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one('property.details', string='Property')
    image = fields.Image(string='Image ')
    video_url = fields.Char("Video URL",
                            help="URL of a video for showcasing your property.")
    embed_code = fields.Html(compute="_compute_embed_code",
                             sanitize=False)
    can_image_1024_be_zoomed = fields.Boolean(string="Can Image 1024 be zoomed",
                                              compute="_compute_can_image_1024_be_zoomed",
                                              store=True)

    @api.depends("image", "image_1024")
    def _compute_can_image_1024_be_zoomed(self):
        for image in self:
            image.can_image_1024_be_zoomed = (
                image.image and tools.is_image_size_above(image.image, image.image_1024))

    @api.onchange("video_url")
    def _onchange_video_url(self):
        if not self.image:
            thumbnail = get_video_thumbnail(self.video_url)
            self.image = thumbnail and base64.b64encode(thumbnail) or False

    @api.depends("video_url")
    def _compute_embed_code(self):
        for image in self:
            image.embed_code = get_video_embed_code(image.video_url) or False

    @api.constrains("video_url")
    def _check_valid_video_url(self):
        for image in self:
            if image.video_url and not image.embed_code:
                raise ValidationError(
                    _(
                        "Provided video URL for '%s' is not valid. Please enter a valid video URL.",
                        image.name,
                    )
                )


# Property Images
class PropertyImages(models.Model):
    _name = 'property.images'
    _description = 'Property Images'
    _inherit = ["image.mixin"]
    _order = "sequence, id"

    title = fields.Char(string='Title', translate=True)
    sequence = fields.Integer(default=10)
    property_id = fields.Many2one('property.details',
                                  string='Property Name',
                                  readonly=True)
    image = fields.Image(string='Images')
    video_url = fields.Char("Video URL",
                            help="URL of a video for showcasing your property.")
    embed_code = fields.Html(compute="_compute_embed_code",
                             sanitize=False)
    can_image_1024_be_zoomed = fields.Boolean(string="Can Image 1024 be zoomed",
                                              compute="_compute_can_image_1024_be_zoomed",
                                              store=True)

    @api.depends("image", "image_1024")
    def _compute_can_image_1024_be_zoomed(self):
        for image in self:
            image.can_image_1024_be_zoomed = (
                image.image and tools.is_image_size_above(image.image, image.image_1024))

    @api.onchange("video_url")
    def _onchange_video_url(self):
        if not self.image:
            thumbnail = get_video_thumbnail(self.video_url)
            self.image = thumbnail and base64.b64encode(thumbnail) or False

    @api.depends("video_url")
    def _compute_embed_code(self):
        for image in self:
            image.embed_code = get_video_embed_code(image.video_url) or False

    @api.constrains("video_url")
    def _check_valid_video_url(self):
        for image in self:
            if image.video_url and not image.embed_code:
                raise ValidationError(
                    _(
                        "Provided video URL for '%s' is not valid. Please enter a valid video URL.",
                        image.name,
                    )
                )


# Property Tags
class PropertyTag(models.Model):
    _name = 'property.tag'
    _description = 'Property Tags'
    _rec_name = 'title'

    title = fields.Char(string='Title', translate=True)
    color = fields.Integer(string='Color')

    def unlink(self):
        for rec in self:
            # Prevent deletion if referenced by any property
            prop_count = self.env['property.details'].search_count([
                ('tag_ids', 'in', rec.id)
            ])
            if prop_count:
                raise ValidationError(
                    _("Cannot delete tag because it is referenced by properties"))
        return super(PropertyTag, self).unlink()


# Utility Service
class TenancyExtraService(models.Model):
    _inherit = 'product.product'

    is_extra_service_product = fields.Boolean(string="Is Extras Service")


# Utility Service Line
class ExtraServiceLine(models.Model):
    _name = 'extra.service.line'
    _description = "Tenancy Extras Service"

    service_id = fields.Many2one('product.product',
                                 string="Service",
                                 domain=[('is_extra_service_product', '=', True)])
    price = fields.Float(string="Cost")
    service_type = fields.Selection([('once', 'Once'),
                                     ('monthly', 'Recurring')],
                                    string="Type",
                                    default="once")
    property_id = fields.Many2one('property.details',
                                  string="Property")

    @api.onchange('service_id')
    def _onchange_service_id_price(self):
        for rec in self:
            if rec.service_id:
                rec.price = rec.service_id.lst_price


# City
class PropertyResCity(models.Model):
    _name = 'property.res.city'
    _description = 'Cities'

    color = fields.Integer('Color')
    name = fields.Char(string="City Name", required=True, translate=True)


# Property Connectivity
class PropertyConnectivity(models.Model):
    _name = 'property.connectivity'
    _description = "Property Nearby Connectivity"

    name = fields.Char(string="Title", translate=True)
    distance = fields.Char(string="Distance", translate=True)
    image = fields.Image(string='Images')


# Property Connectivity Line
class PropertyConnectivityLine(models.Model):
    _name = 'property.connectivity.line'
    _description = "Property Connectivity Line"

    property_id = fields.Many2one('property.details')
    connectivity_id = fields.Many2one('property.connectivity',
                                      string="Nearby Connectivity")
    name = fields.Char(string="Name", translate=True)
    image = fields.Image(related="connectivity_id.image", string='Images')
    distance = fields.Char(string="Distance", translate=True)



# Sale Inquiry
class SaleInquiry(models.Model):
    _name = 'sale.inquiry'
    _description = "Sale Inquiry"
    _rec_name = 'lead_id'

    property_id = fields.Many2one('property.details',
                                  string="Property Details")
    note = fields.Text(string="Note", translate=True)
    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency')
    ask_price = fields.Monetary(string="Ask Price")
    customer_id = fields.Many2one('res.partner',
                                  string="Customer")
    lead_id = fields.Many2one('crm.lead',
                              string="Lead")

    def name_get(self):
        data = []
        for rec in self:
            if rec.lead_id:
                data.append((rec.id, '%s - %s' %
                             (rec.customer_id.name, rec.lead_id.name)))
            else:
                data.append((rec.id, '%s' % rec.customer_id.name))
        return data


# Property Area Type
class PropertyAreaType(models.Model):
    _name = 'property.area.type'
    _description = "Property Area Type"

    name = fields.Char(string="Title")
    type = fields.Selection([('room', 'Rooms'),
                             ('bathroom', 'Bathrooms'),
                             ('parking', 'Parking'),
                             ('hall', 'Hall'),
                             ('kitchen', 'Kitchen'),
                             ('other', 'Other')], string="Type")

    def unlink(self):
        for rec in self:
            # Prevent deletion if referenced by any area measurement line
            room_count = self.env['property.room.measurement'].search_count([
                ('name', '=', rec.name)
            ])
            if room_count:
                raise ValidationError(
                    _("Cannot delete area type because it may be referenced by measurements"))
        return super(PropertyAreaType, self).unlink()


# Property Sub Type
class PropertySubType(models.Model):
    _name = 'property.sub.type'
    _description = "Property Sub Type"

    name = fields.Char(string="Title")
    type = fields.Selection([('land', 'Land'),
                             ('residential', 'Residential'),
                             ('commercial', 'Commercial'),
                             ('industrial', 'Industrial')],
                            string="Type")
    sequence = fields.Integer()

    def unlink(self):
        for rec in self:
            prop_count = self.env['property.details'].search_count([
                ('property_subtype_id', '=', rec.id)
            ])
            project_count = self.env['property.project'].search_count([
                ('property_subtype_id', '=', rec.id)
            ])
            if prop_count or project_count:
                raise ValidationError(
                    _("Cannot delete property sub type because it is referenced by other records"))
        return super(PropertySubType, self).unlink()


# Furnishing Type
class PropertyFurnishing(models.Model):
    _name = 'property.furnishing'
    _description = "Property Furnishing"

    name = fields.Char(string="Title")

    def unlink(self):
        for rec in self:
            prop_count = self.env['property.details'].search_count([
                ('furnishing_id', '=', rec.id)
            ])
            if prop_count:
                raise ValidationError(
                    _("Cannot delete furnishing because it is referenced by properties"))
        return super(PropertyFurnishing, self).unlink()


# Increment history
class IncrementHistory(models.Model):
    _name = 'increment.history'
    _description = "Increment History"
    _rec_name = "contract_ref"

    property_id = fields.Many2one('property.details', string="Property")
    date = fields.Date(string="Date", default=fields.Date.today())
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', string='Currency')
    contract_ref = fields.Char(string="Contract Ref.")
    rent_type = fields.Selection([('fixed', 'Fixed'), ('area_wise', 'Area Wise')],
                                 string="Pricing Type")
    rent_increment_type = fields.Selection([('fix', 'Fix Amount'), ('percentage', 'Percentage')],
                                           string="Increment Type", default="fix")
    increment_percentage = fields.Float(string="Increment(%)", default=1)
    increment_amount = fields.Monetary(string="Increment Amount")
    previous_rent = fields.Monetary(string="Previous Rent")
    incremented_rent = fields.Monetary(string="Final Rent")


# DEPRECATED MODEL START---------------------------------------------------------------------------------------
class PropertyCommercialMeasurement(models.Model):
    _name = 'property.commercial.measurement'
    _description = 'Commercial Property Measurement Details'

    shops = fields.Char(string='Section', translate=True)
    length = fields.Integer(string='Length')
    width = fields.Integer(string='Width')
    height = fields.Integer(string='Height')
    carpet_area = fields.Integer(string='Area', compute='_compute_carpet_area')
    measure = fields.Char(string='ft²', default='ft²',
                          readonly=True, translate=True)
    commercial_measurement_id = fields.Many2one(
        'property.details', string='Commercial Details')
    no_of_unit = fields.Integer(string="No of Unit", default=1)
    measure_unit = fields.Selection(
        related="commercial_measurement_id.measure_unit", store=True)
    sq_ft = fields.Float(string="Total Square Feet",
                         compute='_compute_carpet_area')
    sq_m = fields.Float(string="Total Square Meters",
                        compute='_compute_carpet_area')
    sq_yd = fields.Float(string="Total Square Yards",
                         compute='_compute_carpet_area')
    cu_ft = fields.Float(string="Total Cubic Feet",
                         compute='_compute_carpet_area')
    cu_m = fields.Float(string="Total Cubic Meters",
                        compute='_compute_carpet_area')

    @api.depends('length', 'width', 'height', 'measure_unit', 'no_of_unit')
    def _compute_carpet_area(self):
        for rec in self:
            total = 0
            sq_ft = 0
            sq_m = 0
            sq_yd = 0
            cu_ft = 0
            cu_m = 0
            if rec.length and rec.width:
                total = rec.length * rec.width * rec.no_of_unit
            if rec.measure_unit == 'sq_ft':
                sq_ft = total
                sq_m = total * 0.092903
                sq_yd = total * 0.111111
                cu_ft = total * rec.height
                cu_m = cu_ft * 0.0283168
            elif rec.measure_unit == 'sq_m':
                sq_ft = total * 10.764
                sq_m = total
                sq_yd = total * 1.19599
                cu_ft = total * rec.height * 35.3147
                cu_m = total * rec.height
            elif rec.measure_unit == 'sq_yd':
                sq_ft = total * 9
                sq_m = total * 0.836127
                sq_yd = total
                cu_ft = total * rec.height * 27
                cu_m = cu_ft / 35.3147
            elif rec.measure_unit == 'cu_ft' and rec.height > 0:
                cu_ft = total * rec.height
                sq_ft = cu_ft / rec.height
                sq_m = (cu_ft / rec.height) * 0.092903
                sq_yd = cu_ft / (rec.height / 3)
                cu_m = cu_ft * 0.0283168
            elif rec.measure_unit == 'cu_m' and rec.height > 0:
                cu_m = total * rec.height
                sq_ft = (cu_m / rec.height) * 10.764
                sq_m = cu_m / rec.height
                sq_yd = (cu_m / 1.0) / (rec.height * 1.0936)
                cu_ft = cu_m * 35.315
            rec.carpet_area = total
            rec.sq_ft = sq_ft
            rec.sq_m = sq_m
            rec.sq_yd = sq_yd
            rec.cu_ft = cu_ft
            rec.cu_m = cu_m


class PropertyIndustrialMeasurement(models.Model):
    _name = 'property.industrial.measurement'
    _description = 'Industrial Property Measurement Details'

    asset = fields.Char(string='industrial Asset', translate=True)
    length = fields.Integer(string='Length')
    width = fields.Integer(string='Width')
    height = fields.Integer(string='Height')
    carpet_area = fields.Integer(string='Area', compute='_compute_carpet_area')
    measure = fields.Char(string='ft²', default='ft²',
                          readonly=True, translate=True)
    industrial_measurement_id = fields.Many2one(
        'property.details', string='Industrial Details')
    no_of_unit = fields.Integer(string="No of Unit", default=1)
    measure_unit = fields.Selection(
        related="industrial_measurement_id.measure_unit", store=True)
    sq_ft = fields.Float(string="Total Square Feet",
                         compute='_compute_carpet_area')
    sq_m = fields.Float(string="Total Square Meters",
                        compute='_compute_carpet_area')
    sq_yd = fields.Float(string="Total Square Yards",
                         compute='_compute_carpet_area')
    cu_ft = fields.Float(string="Total Cubic Feet",
                         compute='_compute_carpet_area')
    cu_m = fields.Float(string="Total Cubic Meters",
                        compute='_compute_carpet_area')

    @api.depends('length', 'width', 'height', 'measure_unit', 'no_of_unit')
    def _compute_carpet_area(self):
        for rec in self:
            total = 0
            sq_ft = 0
            sq_m = 0
            sq_yd = 0
            cu_ft = 0
            cu_m = 0
            if rec.length and rec.width:
                total = rec.length * rec.width * rec.no_of_unit
            if rec.measure_unit == 'sq_ft':
                sq_ft = total
                sq_m = total * 0.092903
                sq_yd = total * 0.111111
                cu_ft = total * rec.height
                cu_m = cu_ft * 0.0283168
            elif rec.measure_unit == 'sq_m':
                sq_ft = total * 10.764
                sq_m = total
                sq_yd = total * 1.19599
                cu_ft = total * rec.height * 35.3147
                cu_m = total * rec.height
            elif rec.measure_unit == 'sq_yd':
                sq_ft = total * 9
                sq_m = total * 0.836127
                sq_yd = total
                cu_ft = total * rec.height * 27
                cu_m = cu_ft / 35.3147
            elif rec.measure_unit == 'cu_ft' and rec.height > 0:
                cu_ft = total * rec.height
                sq_ft = cu_ft / rec.height
                sq_m = (cu_ft / rec.height) * 0.092903
                sq_yd = cu_ft / (rec.height / 3)
                cu_m = cu_ft * 0.0283168
            elif rec.measure_unit == 'cu_m' and rec.height > 0:
                cu_m = total * rec.height
                sq_ft = (cu_m / rec.height) * 10.764
                sq_m = cu_m / rec.height
                sq_yd = (cu_m / 1.0) / (rec.height * 1.0936)
                cu_ft = cu_m * 35.315
            rec.carpet_area = total
            rec.sq_ft = sq_ft
            rec.sq_m = sq_m
            rec.sq_yd = sq_yd
            rec.cu_ft = cu_ft
            rec.cu_m = cu_m


class CertificateType(models.Model):
    _name = 'certificate.type'
    _description = 'Type Of Certificate'
    _rec_name = 'type'

    type = fields.Char(string='Type', translate=True)

    def unlink(self):
        for rec in self:
            cert_count = self.env['property.certificate'].search_count([
                ('type_id', '=', rec.id)
            ])
            if cert_count:
                raise ValidationError(
                    _("Cannot delete certificate type because it is referenced by property certificates"))
        return super(CertificateType, self).unlink()


class PropertyCertificate(models.Model):
    _name = 'property.certificate'
    _description = 'Property Related All Certificate'
    _rec_name = 'type_id'

    type_id = fields.Many2one('certificate.type', string='Type')
    expiry_date = fields.Date(string='Expiry Date')
    responsible = fields.Char(string='Responsible', translate=True)
    note = fields.Char(string='Note', translate=True)
    property_id = fields.Many2one('property.details', string='Property')


class ParentProperty(models.Model):
    _name = 'parent.property'
    _description = 'Parent Property Details'

    name = fields.Char(string='Name', translate=True)
    image = fields.Binary(string='Image')
    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)
    amenities_ids = fields.Many2many('property.amenities', string='Amenities')
    property_specification_ids = fields.Many2many('property.specification',
                                                  string='Specification')
    zip = fields.Char(string='Zip')
    street = fields.Char(string='Street1', translate=True)
    street2 = fields.Char(string='Street2', translate=True)
    city = fields.Char(string='City ', translate=True)
    city_id = fields.Many2one('property.res.city', string='City')
    country_id = fields.Many2one('res.country', 'Country')
    state_id = fields.Many2one("res.country.state",
                               string='State',
                               readonly=False, store=True,
                               domain="[('country_id', '=?', country_id)]")
    # Removed landlord from parent property
    website = fields.Char(string='Website', translate=True)
    airport = fields.Char(string='Airport')
    national_highway = fields.Char(string='National Highway', translate=True)
    metro_station = fields.Char(string='Metro Station', translate=True)
    metro_city = fields.Char(string='Metro City', translate=True)
    school = fields.Char(string="School", translate=True)
    hospital = fields.Char(string="Hospital", translate=True)
    shopping_mall = fields.Char(string="Mall", translate=True)
    park = fields.Char(string="Park", translate=True)
    type = fields.Selection([('residential', 'Residential'),
                             ('commercial', 'Commercial'),
                             ('industrial', 'Industrial')],
                            string='Property Type',
                            default="residential")
    property_count = fields.Integer(string="Property Count",
                                    compute="_compute_properties")

    # Residential
    residence_type = fields.Selection([('apartment', 'Apartment'),
                                       ('bungalow', 'Bungalow'),
                                       ('vila', 'Vila'),
                                       ('raw_house', 'Raw House'),
                                       ('duplex', 'Duplex House'),
                                       ('single_studio', 'Single Studio')],
                                      string='Type of Residence')
    total_floor = fields.Integer(string='Total Floor')
    towers = fields.Boolean(string='Tower Building')
    no_of_towers = fields.Integer(string='No. of Towers')

    # Commercial
    commercial_type = fields.Selection([('full_commercial', 'Full Commercial'),
                                        ('shops', 'Shops'),
                                        ('big_hall', 'Big Hall')],
                                       string='Commercial Type')

    # Industrial
    industry_location = fields.Selection([('inside', 'Inside City'),
                                          ('outside', 'Outside City')],
                                         string='Location')

    def _compute_properties(self):
        for rec in self:
            rec.property_count = self.env['property.details'].search_count(
                [('parent_property_id', '=', rec.id), ('is_parent_property', '=', True)])

    def action_properties_parent(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Properties',
            'res_model': 'property.details',
            'domain': [('parent_property_id', '=', self.id), ('is_parent_property', '=', True)],
            'context': {'default_parent_property_id': self.id, 'default_is_parent_property': True},
            'view_mode': 'kanban,tree,form',
            'target': 'current'
        }

# ------------------------------------------------------------------------------------------DEPRECATED MODEL END

    @api.onchange('subproject_id')
    def _onchange_subproject_defaults(self):
        for rec in self:
            sp = rec.subproject_id
            if sp:
                if not rec.sale_tax_ids and getattr(sp, 'sale_tax_ids', False):
                    rec.sale_tax_ids = [(6, 0, sp.sale_tax_ids.ids)]
                if not rec.foreign_currency_id and getattr(sp, 'foreign_currency_id', False):
                    rec.foreign_currency_id = sp.foreign_currency_id
                if not rec.exchange_rate and getattr(sp, 'exchange_rate', False):
                    rec.exchange_rate = sp.exchange_rate
                if not rec.pricelist_id and getattr(sp, 'pricelist_id', False):
                    rec.pricelist_id = sp.pricelist_id
                if not rec.subproject_price_config_id and getattr(sp, 'price_config_id', False):
                    rec.subproject_price_config_id = sp.price_config_id

    def action_apply_subproject_price_config(self):
        for rec in self:
            cfg = rec.subproject_price_config_id or (rec.subproject_id and rec.subproject_id.price_config_id)
            if cfg:
                rec.price = cfg.price
        return True

    @api.onchange('sale_tax_ids')
    def _onchange_sale_tax_ids_sync_product(self):
        for rec in self:
            if rec.product_id:
                rec.product_id.taxes_id = [(6, 0, rec.sale_tax_ids.ids)]

    @api.onchange('product_id')
    def _onchange_product_id_sync_taxes(self):
        for rec in self:
            if rec.product_id:
                if rec.sale_tax_ids:
                    rec.product_id.taxes_id = [(6, 0, rec.sale_tax_ids.ids)]
                # Default unit category from product if not set
                if not rec.categ_id and rec.product_id.categ_id:
                    rec.categ_id = rec.product_id.categ_id

    @api.onchange('categ_id')
    def _onchange_categ_id_sync_product(self):
        for rec in self:
            if rec.product_id and rec.categ_id:
                rec.product_id.categ_id = rec.categ_id.id
