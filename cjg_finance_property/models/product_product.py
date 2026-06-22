# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import api, fields, models, _

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    product_tmpl_id = fields.Many2one(
        'product.template', related='product_id.product_tmpl_id', string="Product Template")


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    product_tmpl_id = fields.Many2one(
        'product.template', related='product_id.product_tmpl_id', string="Product Template")
    custom_property_ok = fields.Boolean(
        related='product_tmpl_id.custom_property_ok'
    )

class ProductProduct(models.Model):
    _inherit = 'product.product'

    unit_count = fields.Integer(string='Units', compute='_compute_unit_count')

    # Campos relacionados desde product.template para soportar dominios y relaciones
    custom_property_ok = fields.Boolean(related='product_tmpl_id.custom_property_ok', store=True)
    is_available_for_credit = fields.Boolean(related='product_tmpl_id.is_available_for_credit', store=True)
    adicional_project_ok = fields.Boolean(related='product_tmpl_id.adicional_project_ok', store=True)

    project_property_id = fields.Many2one('property.sub.project', related='product_tmpl_id.project_property_id', store=True)
    project_property_id_adicional = fields.Many2one('property.sub.project', related='product_tmpl_id.project_property_id_adicional', store=True)

    def _compute_unit_count(self):
        Property = self.env['property.details']
        for rec in self:
            rec.unit_count = Property.search_count([('product_id', '=', rec.product_tmpl_id.id)])

    def action_view_units(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Units',
            'res_model': 'property.details',
            'view_mode': 'form,tree',
            'target': 'current',
            'domain': [('product_id', '=', self.product_tmpl_id.id)],
            'context': {'create': False},
        }

    def write(self, vals):
        # Permitir escribir sin advertencias; la vista se encarga del modo lectura
        return super(ProductProduct, self).write(vals)