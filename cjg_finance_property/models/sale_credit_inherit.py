# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError

# Únicos estados en los que una propiedad puede ser asignada a un contrato
ASSIGNABLE_STAGES = ('available',)

# Etiquetas legibles para los mensajes de error
STAGE_LABELS = {
    'draft':    'Borrador',
    'available':'Disponible',
    'booked':   'En Reserva',
    'sale':     'En Venta',
    'sold':     'Vendida',
    'occupied': 'Con Inhumado',
}


class SaleCreditPropertyInherit(models.Model):
    _inherit = 'sale.credit'
    
    # Extend contract_product_type to include 'property' option
    contract_product_type = fields.Selection(
        selection_add=[('property', 'Propiedad')],
        ondelete={'property': 'set default'}
    )
    
    # Add property_product_ids Many2many field
    property_product_ids = fields.Many2many(
        'property.details',
        'sale_credit_property_rel',
        'credit_id',
        'property_id',
        string='Propiedades',
        domain="[('active', '=', True), ('stage', '=', 'available')]",
        help="Propiedades asociadas a este contrato (solo activas y disponibles)"
    )

    @api.constrains('property_product_ids')
    def _check_property_stages(self):
        """Impide asignar propiedades que no estén en estado 'Disponible'."""
        if self.env.context.get('force_migration'):
            return  # La migración puede asignar cualquier propiedad
        for record in self:
            bad = record.property_product_ids.with_context(active_test=False).filtered(
                lambda p: p.stage not in ASSIGNABLE_STAGES
            )
            if bad:
                details = ', '.join(
                    f"{p.name} [{STAGE_LABELS.get(p.stage, p.stage)}]"
                    for p in bad
                )
                raise ValidationError(
                    f"No se pueden asignar propiedades que no estén Disponibles:\n{details}\n\n"
                    f"Solo se permiten propiedades en estado: Disponible."
                )

    # Override total_sold to compute from products
    total_sold = fields.Float(
        string="Total Vendido",
        compute='_compute_total_from_products',
        store=True,
        readonly=False
    )
    
    
    @api.depends('property_product_ids', 'property_product_ids.price', 
                 'property_product_ids.product_id', 'property_product_ids.product_id.list_price',
                 'contract_product_type')
    def _compute_total_from_products(self):
        """Calculate total_sold from property products"""
        for record in self:
            if record.contract_product_type == 'property' and record.property_product_ids:
                # Sumar precios de propiedades (usar price o product_id.list_price)
                total = 0
                for prop in record.property_product_ids:
                    # Prefer property.price, fallback to product list_price
                    prop_price = prop.price or (prop.product_id.list_price if prop.product_id else 0)
                    total += prop_price or 0
                record.total_sold = total
            else:
                # Si no es property type o no hay propiedades, mantener valor actual
                if not record.total_sold:
                    record.total_sold = 0.0
    
    @api.onchange('property_product_ids', 'contract_product_type')
    def _onchange_products(self):
        """Trigger recalculation when products change"""
        if self.contract_product_type == 'property' and self.property_product_ids:
            # Calculate total from properties
            total = 0
            for prop in self.property_product_ids:
                # If it's a NewId, get the real record from database
                if isinstance(prop.id, models.NewId):
                    real_id = prop.id.origin
                    if real_id:
                        # Fetch property data using read() to force DB fetch
                        prop_data = self.env['property.details'].browse(real_id).read(['price', 'product_id'])[0]
                        product_price = 0
                        if prop_data.get('product_id'):
                            product_id = prop_data['product_id'][0]
                            product_data = self.env['product.template'].browse(product_id).read(['list_price'])[0]
                            product_price = product_data.get('list_price', 0)
                        
                        prop_price = prop_data.get('price', 0) or product_price
                    else:
                        prop_price = 0
                else:
                    # Regular record
                    prop_price = prop.price or (prop.product_id.list_price if prop.product_id else 0)
                    
                total += prop_price or 0
                
            self.total_sold = total
            
            # Trigger financing calculations
            if self.total_sold and self.category_id:
                if self.percent_financing == 0:
                    self.percent_financing = self.category_id.percent_financing
                min_pay = self.total_sold * (self.percent_financing / 100)
                self.min_amount = self.total_sold - min_pay
                self.amount_financed = min_pay
    
    def write(self, vals):
        """Override write to handle property removal and release them to available"""
        # Check if property_product_ids is being modified
        if 'property_product_ids' in vals:
            # Bloquear propiedades INACTIVAS (archivadas) fuera del contexto de migración
            if not self.env.context.get('force_migration'):
                # Recolectar IDs que se van a agregar
                ids_to_add = set()
                for cmd in vals.get('property_product_ids', []):
                    if cmd[0] == 6:
                        ids_to_add.update(cmd[2])
                    elif cmd[0] == 4:
                        ids_to_add.add(cmd[1])
                if ids_to_add:
                    props = self.env['property.details'].with_context(active_test=False).browse(list(ids_to_add))

                    # Bloquear propiedades INACTIVAS
                    inactive = props.filtered(lambda p: not p.active)
                    if inactive:
                        names = ', '.join(inactive.mapped('name'))
                        raise ValidationError(
                            f"No se pueden asignar propiedades inactivas/archivadas al contrato: {names}"
                        )

                    # Bloquear propiedades en estado incorrecto
                    wrong_stage = props.filtered(lambda p: p.stage not in ASSIGNABLE_STAGES)
                    if wrong_stage:
                        details = ', '.join(
                            f"{p.name} [{STAGE_LABELS.get(p.stage, p.stage)}]"
                            for p in wrong_stage
                        )
                        raise ValidationError(
                            f"No se pueden asignar propiedades que no estén Disponibles:\n{details}"
                        )

            # Permitir modificación durante migración (contexto especial)
            if not self.env.context.get('force_migration'):
                # Solo usuarios con permiso especial pueden modificar propiedades en contratos activos
                if not self.env.user.has_group('cjg_finance_property.group_property_contract_manager'):
                    if any(rec.state not in ['draft'] for rec in self):
                        from odoo.exceptions import AccessError
                        raise AccessError(
                            "No tienes permisos para modificar propiedades en contratos activos. "
                            "Contacta a un administrador."
                        )
            
            # Detectar propiedades que se están quitando/agregando
            for record in self:
                old_property_ids = set(record.property_product_ids.ids)
                
                # Parsear el comando Many2many
                new_property_ids = set()
                for cmd in vals.get('property_product_ids', []):
                    if cmd[0] == 6:  # (6, 0, [ids]) - replace
                        new_property_ids = set(cmd[2])
                    elif cmd[0] == 4:  # (4, id) - add
                        new_property_ids.add(cmd[1])
                    elif cmd[0] == 3:  # (3, id) - remove
                        new_property_ids.discard(cmd[1])
                
                # Propiedades removidas
                removed_property_ids = old_property_ids - new_property_ids
                # Propiedades agregadas
                added_property_ids = new_property_ids - old_property_ids
                
                if removed_property_ids:
                    removed_properties = self.env['property.details'].browse(removed_property_ids)
                    
                    # Liberar propiedades removidas
                    removed_properties.write({'stage': 'available'})
                    
                    # 📝 TRACKING: Mensaje en el contrato (chatter)
                    property_names = ', '.join(removed_properties.mapped('name'))
                    record.message_post(
                        body=f"<b>🏠 Propiedades Removidas del Contrato</b><br/>"
                             f"<ul>"
                             f"<li><b>Propiedades:</b> {property_names}</li>"
                             f"<li><b>Cantidad:</b> {len(removed_properties)}</li>"
                             f"<li><b>Usuario:</b> {self.env.user.name}</li>"
                             f"<li><b>Estado:</b> Liberadas a 'Disponible'</li>"
                             f"</ul>",
                        subject="Propiedades Removidas",
                        subtype_xmlid='mail.mt_note'
                    )
                    
                    # 📝 TRACKING: Mensaje en cada propiedad liberada
                    for prop in removed_properties:
                        prop.message_post(
                            body=f"<b>🔓 Propiedad Liberada</b><br/>"
                                 f"Removida del contrato <a href='#id={record.id}&model=sale.credit'>{record.name}</a><br/>"
                                 f"<b>Usuario:</b> {self.env.user.name}",
                            subject="Liberada de Contrato",
                            subtype_xmlid='mail.mt_note'
                        )
                
                if added_property_ids:
                    added_properties = self.env['property.details'].browse(added_property_ids)
                    
                    # 📝 TRACKING: Mensaje cuando se agregan propiedades
                    property_names = ', '.join(added_properties.mapped('name'))
                    record.message_post(
                        body=f"<b>🏠 Propiedades Agregadas al Contrato</b><br/>"
                             f"<ul>"
                             f"<li><b>Propiedades:</b> {property_names}</li>"
                             f"<li><b>Cantidad:</b> {len(added_properties)}</li>"
                             f"<li><b>Usuario:</b> {self.env.user.name}</li>"
                             f"</ul>",
                        subject="Propiedades Agregadas",
                        subtype_xmlid='mail.mt_note'
                    )
        
        return super(SaleCreditPropertyInherit, self).write(vals)
    
    def action_solicitud_status(self):
        """Request credit and mark property as in sale"""
        if self.property_product_ids:
            for prop in self.property_product_ids:
                prop.credit_id = self.id
                prop.action_in_sale()
        
        # Call parent action_request_credit if exists
        if hasattr(super(SaleCreditPropertyInherit, self), 'action_request_credit'):
            return super(SaleCreditPropertyInherit, self).action_request_credit()
        else:
            self.state = 'requested'
    
    def action_approve_status(self):
        """Approve credit"""
        # Call parent approve if exists
        if hasattr(super(SaleCreditPropertyInherit, self), 'action_approve_credit'):
            super(SaleCreditPropertyInherit, self).action_approve_credit()
        else:
            self.state = 'approved'
        
        return True
    
    def cancelled(self):
        """Override cancel to release properties"""
        # Release properties
        if self.property_product_ids:
            for prop in self.property_product_ids:
                prop.credit_id = False
                prop.write({'stage': 'available'})
        
        # Call parent cancelled if exists
        if hasattr(super(SaleCreditPropertyInherit, self), 'cancelled'):
            return super(SaleCreditPropertyInherit, self).cancelled()
        else:
            self.state = 'cancelled'
    
    def action_sales_status(self):
        """Create sale order from approved credit"""
        # Call parent action_create_sale if exists
        if hasattr(super(SaleCreditPropertyInherit, self), 'action_create_sale'):
            return super(SaleCreditPropertyInherit, self).action_create_sale()
        else:
            # Basic implementation if parent doesn't have it
            self.state = 'done'
            return True
