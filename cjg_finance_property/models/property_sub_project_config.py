# -*- coding: utf-8 -*-
# Copyright 2023-Today TechKhedut.

import base64
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError
from odoo.addons.web_editor.tools import get_video_embed_code, get_video_thumbnail


# Precio de Lista por Subproyecto
class SubprojectPriceConfig(models.Model):
    _name = 'subproject.price.config'
    
    _description = 'Configuración de Precio por Subproyecto'

    name = fields.Char(string='Nombre', required=True)
    subproject_id = fields.Many2one('property.sub.project', string='Subproyecto', required=False, ondelete='cascade')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    # funeral_location_id = fields.Many2one('crm.funeral.location', string='Ubicación')  # Commented - model doesn't exist here
    currency_id = fields.Many2one('res.currency', related='subproject_id.currency_id', store=True, string='Moneda')
    price = fields.Monetary(string='Precio', currency_field='currency_id', required=True)
    max_qty = fields.Integer(string='Cantidad máxima vendible', default=1,
                              help='Cantidad máxima de unidades que se pueden vender bajo esta configuración (ej. 2 para "Jardines de Familia de 2").')

    # Campos de control
    active = fields.Boolean(string='Activo', default=True, help='Desmarque para archivar esta configuración de precio sin eliminarla')
    valid_from = fields.Date(string='Vigente desde', help='Fecha desde la cual esta configuración de precio es válida')
    valid_to = fields.Date(string='Vigente hasta', help='Fecha hasta la cual esta configuración de precio es válida')
    description = fields.Text(string='Descripción', help='Notas o detalles sobre esta configuración de precio')

    
    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Auto-seleccionar ubicación cuando se cambia la compañía"""
        # Base implementation - can be extended in portal_crm_to_quotation
        pass
    
    @api.constrains('valid_from', 'valid_to')
    def _check_validity_dates(self):
        """Validar que la fecha de inicio sea anterior a la fecha de fin"""
        for rec in self:
            if rec.valid_from and rec.valid_to and rec.valid_from > rec.valid_to:
                raise ValidationError(_(
                    "La fecha 'Vigente desde' debe ser anterior a la fecha 'Vigente hasta'."
                ))

    
    @api.model
    def _update_legacy_records(self):
        """Actualizar registros sin company_id asignado"""
        # Buscar la primera compañía disponible
        company = self.env['res.company'].search([], limit=1)
        if company:
            # Actualizar todos los registros sin company_id
            self.env.cr.execute("""
                UPDATE subproject_price_config
                SET company_id = %s
                WHERE company_id IS NULL
            """, (company.id,))
