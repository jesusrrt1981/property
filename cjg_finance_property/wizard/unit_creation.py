# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


# Unit Create from Project
class UnitCreation(models.TransientModel):
    _name = 'unit.creation'
    _description = 'Project Unit Creation'

    total_floors = fields.Integer(string="Total Floors", default="1")
    units_per_floor = fields.Integer(string="Units per Floor", default="1")
    property_code_prefix = fields.Char(string="Prefix",
                                       help="Prefix for Property Code")
    floor_start_from = fields.Integer(string="Floor Start From")

    # Campos para seguir el formato de nombres del wizard de lands
    letters_type = fields.Char(string="Tipologia", required=True)
    suffix_letters = fields.Char(string="Sufijo (Letras)",
                                 help="Letras que se agregarán al final de cada número (ejemplo: AB)")
    use_padding = fields.Boolean(string="Rellenar con ceros", default=False,
                                 help="Si está marcado, los números se rellenarán con ceros (ej: 0001). Si no, será solo el número (ej: 1)")
    nombre_example = fields.Char(string="Nombre", readonly=True)

    @api.model
    def default_get(self, fields):
        res = super(UnitCreation, self).default_get(fields)
        active_id = self._context.get("active_id", False)
        unit_from = self._context.get('unit_from')
        if unit_from == 'project':
            project_id = self.env["property.project"].browse(active_id)
            res['property_code_prefix'] = project_id.project_sequence
            res['floor_start_from'] = project_id.floor_created + 1
        elif unit_from == 'sub_project':
            project_id = self.env["property.sub.project"].browse(active_id)
            res['property_code_prefix'] = project_id.project_sequence
            res['total_floors'] = project_id.total_floors
            res['units_per_floor'] = project_id.units_per_floor
            res['floor_start_from'] = project_id.floor_created + 1
        return res

    @api.onchange('suffix_letters')
    def _onchange_suffix_letters(self):
        if self.suffix_letters:
            if not self.suffix_letters.isalpha():
                raise ValidationError(_("El sufijo solo debe contener letras"))
            self.suffix_letters = self.suffix_letters.upper()

    def _get_project(self):
        unit_from = self._context.get('unit_from')
        active_id = self._context.get("active_id")
        if unit_from == 'project' and active_id:
            return self.env["property.project"].browse(active_id)
        if unit_from == 'sub_project' and active_id:
            return self.env["property.sub.project"].browse(active_id)
        return False

    def create_name_example(self, floor, unit):
        project = self._get_project()
        # Usar código del proyecto en vez del nombre
        project_code = project.project_sequence if project else ''
        suffix = self.suffix_letters.upper() if self.suffix_letters else ''
        # Aplicar padding solo si está marcado
        if self.use_padding:
            number = f"{str(floor).zfill(4)}"
        else:
            number = str(floor)
        
        name = "{} - {} - {}{}".format(
            project_code,  # Cambiado de project.name a project_code
            str(self.letters_type).upper() if self.letters_type else '',
            number,
            suffix
        )
        return name

    @api.onchange("letters_type", "floor_start_from", "suffix_letters", "use_padding")
    def onchange_letters(self):
        if self.floor_start_from:
            self.nombre_example = self.create_name_example(self.floor_start_from, 1)

    def action_create_property_unit(self):
        created_ids = []
        active_id = self._context.get("active_id", False)
        unit_from = self._context.get('unit_from')
        property_rec = {}
        project_id = False
        if self.total_floors <= 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'title': _('Total Floor !'),
                    'message': _("Total floor should be greater than 1."),
                    'sticky': False,
                }
            }
        if self.units_per_floor <= 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'title': _('Total Unit Per Floor !'),
                    'message': _('Total unit per floor should be greater than 1.'),
                    'sticky': False,
                }
            }
        if not active_id:
            return
        if unit_from == 'project':
            project_id = self.env["property.project"].browse(active_id)
            property_rec['property_project_id'] = project_id.id
        elif unit_from == 'sub_project':
            project_id = self.env["property.sub.project"].browse(active_id)
            property_rec['property_project_id'] = project_id.property_project_id.id
            property_rec['subproject_id'] = project_id.id
        if not project_id:
            return
        if project_id.project_for == 'sale':
            property_rec['sale_lease'] = 'for_sale'
        property_static_rec = {
            'total_floor': self.total_floors,
            'property_subtype_id': project_id.property_subtype_id.id,
            'type': project_id.property_type,
            'street': project_id.street,
            'street2': project_id.street2,
            'city_id': project_id.city_id.id,
            'zip': project_id.zip,
            'state_id': project_id.state_id.id,
            'country_id': project_id.country_id.id,
            'region_id': project_id.region_id.id,
            'website': project_id.website,
            'longitude': project_id.longitude,
            'latitude': project_id.latitude,
        }
        property_rec.update(property_static_rec)
        property_data = []
        for floor in range(self.floor_start_from, self.total_floors + self.floor_start_from):
            for unit in range(1, self.units_per_floor + 1):
                code = "%s%s-%s" % (self.property_code_prefix,
                                    str(floor).zfill(2), str(unit).zfill(2))
                name = self.create_name_example(floor, unit)
                floor_now = floor
                property_data.append({
                    "name": name,
                    "property_seq": code,
                    "floor": floor_now
                })
        unit_amenities, unit_images, unit_specification = self.get_property_availability(
            unit_from=unit_from,
            project_id=project_id
        )
        availability_info = self.get_property_availability_info(
            project_id=project_id,
            unit_amenities=unit_amenities,
            unit_specification=unit_specification,
            unit_images=unit_images
        )
        property_rec.update(availability_info)
        
        # Obtener precio de venta desde price_config_id del subproyecto
        sale_price = 0
        if unit_from == 'sub_project' and project_id.price_config_id:
            sale_price = project_id.price_config_id.price or 0
        
        # Property Data
        for data in property_data:
            property_rec['name'] = data.get('name')
            property_rec['property_seq'] = data.get('property_seq')
            property_rec['floor'] = data.get('floor')
            property_rec['sale_price'] = sale_price  # ⭐ Agregar precio de venta
            property_rec['stage'] = 'available'  # ⭐ Crear como disponible por defecto
            property_id = self.env['property.details'].sudo().create(
                property_rec)
            created_ids.append(property_id.id)
        project_id.write({
            'total_floors': self.total_floors,
            'units_per_floor': self.units_per_floor,
            'floor_created': project_id.floor_created + self.total_floors
        })
        return {
            "name": "Properties",
            "type": "ir.actions.act_window",
            "domain": [("id", "in", created_ids)],
            "view_mode": "tree,form",
            'context': {'create': False},
            "res_model": "property.details",
            "target": "current",
        }

    def get_property_availability(self, unit_from, project_id):
        unit_amenities = False
        unit_images = False
        unit_specification = False
        if unit_from == 'project':
            unit_amenities = project_id.property_amenity_ids.ids
            unit_images = project_id.project_image_ids
            unit_specification = project_id.property_specification_ids.ids
        if unit_from == 'sub_project':
            unit_amenities = project_id.subproject_amenity_ids.ids
            # Fallback: usar imágenes del proyecto principal, ya no existen imágenes a nivel de subproyecto
            unit_images = project_id.project_image_ids
            unit_specification = project_id.subproject_specification_ids.ids
        return unit_amenities, unit_images, unit_specification

    def get_property_availability_info(self, project_id, unit_amenities, unit_specification, unit_images):
        info_rec = {}
        images = []
        nearby = []
        # Amenities
        if project_id.avail_amenity:
            info_rec['amenities'] = project_id.avail_amenity
            info_rec['amenities_ids'] = unit_amenities
        # Specifications
        if project_id.avail_specification:
            info_rec['is_facilities'] = project_id.avail_specification
            info_rec['property_specification_ids'] = unit_specification
        # Images
        if project_id.avail_image:
            info_rec['is_images'] = project_id.avail_image
            for image in unit_images:
                images.append((0, 0, {
                    'title': image.title,
                    'sequence': image.sequence,
                    'image': image.image,
                    'video_url': image.video_url,
                }))
            info_rec['property_images_ids'] = images
        # Connectivity
        return info_rec
