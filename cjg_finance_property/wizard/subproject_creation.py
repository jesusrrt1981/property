# -*- coding: utf-8 -*-
# Copyright 2023-Today TechKhedut.



from odoo import api, fields, models


class SubprojectCreation(models.TransientModel):
    _name = "subproject.creation"
    _description = "Create Sub Project"

    name = fields.Char(string="Name", required=True)
    project_sequence = fields.Char(string="Code", required=True)
    floors = fields.Integer(string="No. of Floors", default=1)
    units_per_floor = fields.Integer(string="Units per Floor", default=1)

    def create_sub_project(self):
        nearby = []
        active_id = self._context.get("active_id", False)
        if not active_id:
            return
        project_id = self.env["property.project"].browse(active_id)
        data = {
            "name": self.name,
            "project_sequence": self.project_sequence,
            "property_project_id": project_id.id,
            "property_type": project_id.property_type,
            "property_subtype_id": project_id.property_subtype_id.id,
            "country_id": project_id.country_id.id,
            "street": project_id.street,
            "street2": project_id.street2,
            "city_id": project_id.city_id.id,
            "state_id": project_id.state_id.id,
            "property_brochure": project_id.property_brochure,
            "brochure_name": project_id.brochure_name,
            "zip": project_id.zip,
            "image_1920": project_id.image_1920,
            "total_floors": self.floors,
            "units_per_floor": self.units_per_floor,
            'sale_lease': project_id.sale_lease
        }
        if project_id.avail_description:
            data['avail_description'] = project_id.avail_description
            data['description'] = project_id.description
        if project_id.avail_amenity:
            data['avail_amenity'] = project_id.avail_amenity
            data['subproject_amenity_ids'] = project_id.property_amenity_ids.ids
        if project_id.avail_specification:
            data['avail_specification'] = project_id.avail_specification
            data['subproject_specification_ids']= project_id.property_specification_ids.ids
        if project_id.avail_image:
            # Se copia el indicador de disponibilidad de imágenes, pero no se gestionan imágenes a nivel de subproyecto
            data['avail_image'] = project_id.avail_image

        sub_project_id = self.env["property.sub.project"].create(data)
        return {
            'type': 'ir.actions.act_window',
            'name': ('Sub Projects'),
            'res_model': 'property.sub.project',
            'res_id': sub_project_id.id,
            'view_mode': 'form',
            'target': 'current'
        }
