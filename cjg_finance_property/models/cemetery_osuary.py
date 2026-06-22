# -*- coding: utf-8 -*-
"""
Catálogo de Osarios (testarossa/sp_osarios o campo osario en inventario_jardines).

Un osario es una unidad dentro de una parcela para depositar restos cremados.
"""
from odoo import models, fields, api, _


class CemeteryOsuary(models.Model):
    _name = 'cemetery.osuary'
    _description = 'Osario (Catálogo)'
    _order = 'code'

    name = fields.Char(
        string='Nombre',
        required=True,
        help='Ej: "A-1", "B-3", etc.',
    )
    code = fields.Char(
        string='Código',
        required=True,
    )
    garden_id = fields.Many2one(
        'cemetery.garden',
        string='Jardín',
    )
    phase_id = fields.Many2one(
        'cemetery.phase',
        string='Fase',
    )
    block = fields.Char(
        string='Bloque',
    )
    lot = fields.Char(
        string='Lote',
    )
    property_id = fields.Many2one(
        'property.details',
        string='Parcela',
        domain="[('space_type', '=', 'ossuary')]",
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
    )
