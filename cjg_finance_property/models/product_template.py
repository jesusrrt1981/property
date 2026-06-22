# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    unit_count = fields.Integer(string='Units', compute='_compute_unit_count')
    # Campos de relación únicamente (sin compute/depends de precio en producto)
    custom_property_ok = fields.Boolean(
        string='Es Propiedad', 
        compute='_compute_custom_property_ok',
        store=True,
        help='Verdadero cuando el producto tiene land_id'
    )
    is_available_for_credit = fields.Boolean(
        string='Disponible para Crédito', 
        compute='_compute_is_available_for_credit',
        store=True,
        help='Verdadero cuando el land_id tiene estado Available o Sale'
    )
    adicional_project_ok = fields.Boolean(string='Es Adicional de Proyecto', default=False)
    # ✅ Debería ser:
    project_property_id = fields.Many2one(
        'property.sub.project', 
        related='land_id.subproject_id',  # Usar el campo correcto
        store=True, 
        string='Proyecto'
    )
    project_property_id_adicional = fields.Many2one('property.sub.project', string='Proyecto Adicional (relación)')

    purchase_line_ids = fields.One2many(
        'purchase.order.line', 'product_tmpl_id', 'Purchase Lines')

    sale_line_ids = fields.One2many('sale.order.line', 'product_tmpl_id', 'Sale Lines')

    project_properties = fields.One2many(
        'product.template',
        compute='_compute_project_properties',
        string="Propiedades del Proyecto"
    )
    
    land_id = fields.Many2one(
        "property.details", 
        string="Parcelas"
    )

    land_ids = fields.Many2many(
        "property.details", 
        string="Solares Aplicables",
        relation="product_template_land_rel",
        column1="product_id",
        column2="land_id",
        compute="_compute_land_ids",
        store=True,
        readonly=True
    )

    # Campos solo para visualización (modo lectura), tomados de property.details
    foreign_currency_id = fields.Many2one('res.currency', string='Moneda extranjera (unidad)', compute='_compute_prop_price_fields')
    prop_exchange_rate = fields.Float(string='Tasa de cambio (unidad)', compute='_compute_prop_price_fields')
    prop_price_foreign = fields.Monetary(
        string='Precio extranjero (unidad)',
        currency_field='foreign_currency_id',
        compute='_compute_prop_price_fields'
    )


    def _compute_unit_count(self):
        Property = self.env['property.details']
        for rec in self:
            rec.unit_count = Property.search_count([('product_id', '=', rec.id)])

    def action_view_units(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Units',
            'res_model': 'property.details',
            'view_mode': 'form,tree',
            'target': 'current',
            'domain': [('product_id', '=', self.id)],
            'context': {'create': False},
        }


    @api.depends('project_property_id')
    def _compute_project_properties(self):
        """Obtiene todas las propiedades del proyecto seleccionado"""
        for record in self:
            if record.project_property_id:
                # Buscar todos los productos que son propiedades (custom_property_ok=True)
                # y pertenecen al proyecto seleccionado
                properties = self.env['product.template'].search([
                    ('custom_property_ok', '=', True),
                    ('project_property_id', '=', record.project_property_id.id)
                ])
                record.project_properties = properties.ids
            else:
                record.project_properties = []

    def _compute_prop_price_fields(self):
        Property = self.env['property.details']
        for rec in self:
            prop = Property.search([('product_id', '=', rec.id)], limit=1)
            if prop:
                rec.foreign_currency_id = prop.foreign_currency_id
                rec.prop_exchange_rate = prop.exchange_rate
                rec.prop_price_foreign = prop.price_foreign
            else:
                rec.foreign_currency_id = False
                rec.prop_exchange_rate = 0.0
                rec.prop_price_foreign = 0.0

    @api.depends('land_id', 'land_id.is_available_for_credit', 'land_id.stage')
    def _compute_is_available_for_credit(self):
        """Compute if product is available for credit based on land_id availability"""
        for rec in self:
            if rec.land_id:
                rec.is_available_for_credit = rec.land_id.is_available_for_credit
            else:
                rec.is_available_for_credit = True  # Default to True if no land_id

    @api.depends('land_id', 'land_id.stage')
    def _compute_custom_property_ok(self):
        """Compute if product is a property based on land_id presence"""
        for rec in self:
            rec.custom_property_ok = bool(rec.land_id)



    @api.depends('project_property_id')
    def _compute_land_ids(self):
        """Actualiza land_ids para incluir todos los solares del proyecto seleccionado"""
        for record in self:
            if record.project_property_id and record.adicional_project_ok:
                # Buscar todos los solares del proyecto seleccionado
                lands = self.env['property.details'].search([
                    ('subproject_id', '=', record.project_property_id.id)
                ])
                record.land_ids = [(6, 0, lands.ids)]
            else:
                record.land_ids = [(5, 0, 0)]  # Limpiar el campo



    @api.model_create_multi
    def create(self, vals_list):
        """Override batch-friendly create to handle project additionals"""
        records = super(ProductTemplate, self).create(vals_list)

        # If it's a project additional, update land_ids per record
        for rec in records:
            if rec.adicional_project_ok and rec.project_property_id:
                rec._compute_land_ids()

        return records
    
    def write(self, vals):
        """Sobreescribimos write para manejar cambios en project_property_id"""
        res = super(ProductTemplate, self).write(vals)
        
        # Si se cambió el proyecto, actualizamos land_ids
        if 'project_property_id' in vals or 'adicional_project_ok' in vals:
            self._compute_land_ids()
            
        return res