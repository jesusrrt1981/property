# -*- coding: utf-8 -*-
# Copyright 2025 CJG
#
# Modelo de cementerio FIEL a Testarossa.
# Reemplaza el uso del módulo genérico de bienes raíces para la gestión
# de jardines y parcelas. Mapeo directo:
#   cemetery.phase          <- tabla `fases`
#   cemetery.garden         <- tabla `jardines`
#   cemetery.garden.pricing <- tabla `jardines_activos` (precio por jardín+fase)

from odoo import api, fields, models, _


class CemeteryPhase(models.Model):
    """Fase: subdivisión geográfica de un jardín (Testarossa: tabla `fases`)."""
    _name = 'cemetery.phase'
    _description = 'Fase de Jardín'
    _order = 'name'

    name = fields.Char(string='Fase', required=True, translate=True)
    code = fields.Char(string='Código', help='id_fases en Testarossa')
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código de fase debe ser único.'),
    ]


class CemeteryGarden(models.Model):
    """Jardín: catálogo de jardines/cementerios (Testarossa: tabla `jardines`)."""
    _name = 'cemetery.garden'
    _description = 'Jardín del Cementerio'
    _order = 'name'

    name = fields.Char(string='Jardín', required=True, translate=True)
    code = fields.Char(string='Código', help='id_jardin en Testarossa')
    abbreviation = fields.Char(string='Abreviatura', help='abreviatura en Testarossa')

    # abrev_tipo_producto en Testarossa: PARCELA / COLUMBAR / JARDIN / OSARIO S / OSARIO P
    space_type = fields.Selection([
        ('parcela', 'Parcela'),
        ('columbario', 'Columbario'),
        ('jardin_familia', 'Jardín de Familia'),
        ('osario_soterrado', 'Osario Soterrado'),
        ('osario_pared', 'Osario de Pared'),
    ], string='Tipo de Espacio', required=True, default='parcela')

    company_id = fields.Many2one(
        'res.company', string='Empresa',
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', string='Moneda')
    currency_usd_id = fields.Many2one(
        'res.currency', string='Moneda USD',
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False))

    pays_fixed_maintenance = fields.Boolean(
        string='Paga Mantenimiento Fijo',
        help='paga_mtto_fijo en Testarossa')
    accounting_group = fields.Integer(
        string='Agrupador Contable', help='agrupador_contable en Testarossa')
    accounting_account_id = fields.Many2one(
        'account.account', string='Cuenta Contable')

    pricing_ids = fields.One2many(
        'cemetery.garden.pricing', 'garden_id', string='Precios por Fase')

    plot_ids = fields.One2many(
        'property.details', 'garden_id', string='Parcelas')
    plot_count = fields.Integer(
        string='Total Parcelas', compute='_compute_plot_stats')
    plot_available_count = fields.Integer(
        string='Disponibles', compute='_compute_plot_stats')
    plot_sold_count = fields.Integer(
        string='Vendidas', compute='_compute_plot_stats')

    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'El código de jardín debe ser único.'),
    ]

    @api.depends('plot_ids', 'plot_ids.stage')
    def _compute_plot_stats(self):
        for garden in self:
            plots = garden.plot_ids
            garden.plot_count = len(plots)
            garden.plot_available_count = len(
                plots.filtered(lambda p: p.stage == 'available'))
            garden.plot_sold_count = len(
                plots.filtered(lambda p: p.stage in ('sold', 'occupied')))

    def name_get(self):
        result = []
        for rec in self:
            name = rec.name
            if rec.abbreviation:
                name = '%s (%s)' % (rec.name, rec.abbreviation)
            result.append((rec.id, name))
        return result


class CemeteryGardenPricing(models.Model):
    """Precio por jardín + fase (Testarossa: tabla `jardines_activos`).

    El precio NO está en la parcela individual: depende del jardín y la fase,
    con variantes Necesidad/Previsión y RD$/US$ (+ precio de osario aparte).
    """
    _name = 'cemetery.garden.pricing'
    _description = 'Precio de Jardín por Fase'
    _order = 'garden_id, phase_id'

    garden_id = fields.Many2one(
        'cemetery.garden', string='Jardín', required=True, ondelete='cascade')
    phase_id = fields.Many2one('cemetery.phase', string='Fase', required=True)
    company_id = fields.Many2one(
        'res.company', related='garden_id.company_id', string='Empresa', store=True)
    currency_id = fields.Many2one(
        'res.currency', related='garden_id.currency_id', string='Moneda RD$')
    currency_usd_id = fields.Many2one(
        'res.currency', related='garden_id.currency_usd_id', string='Moneda US$')

    cost = fields.Monetary(string='Costo', currency_field='currency_id')
    accounting_account_id = fields.Many2one(
        'account.account', string='Cuenta Contable')

    # Necesidad inmediata (NEC en Testarossa)
    price_need_local = fields.Monetary(
        string='Precio Necesidad RD$', currency_field='currency_id')
    price_need_usd = fields.Monetary(
        string='Precio Necesidad US$', currency_field='currency_usd_id')
    # Previsión / preventa (PRE en Testarossa)
    price_prev_local = fields.Monetary(
        string='Precio Previsión RD$', currency_field='currency_id')
    price_prev_usd = fields.Monetary(
        string='Precio Previsión US$', currency_field='currency_usd_id')
    # Precio de osario
    price_ossuary_local = fields.Monetary(
        string='Precio Osario RD$', currency_field='currency_id')
    price_ossuary_usd = fields.Monetary(
        string='Precio Osario US$', currency_field='currency_usd_id')

    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('garden_phase_uniq', 'unique(garden_id, phase_id)',
         'Ya existe un precio para esta combinación de jardín y fase.'),
    ]
