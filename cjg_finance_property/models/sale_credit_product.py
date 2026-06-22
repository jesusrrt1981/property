from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleCreditProduct(models.Model):
    _inherit = 'sale.credit.product'
    
    product_type = fields.Selection(selection_add=[
        ('property', 'Propiedad')
    ], ondelete={'property': 'cascade'})
    
    property_id = fields.Many2one(
        'property.details',
        string='Propiedad'
    )
    
    @api.onchange('property_id')
    def _onchange_property_id(self):
        if self.property_id:
            self.product_type = 'property'
            self.price = self.property_id.price if hasattr(self.property_id, 'price') else 0.0
            self.description = self.property_id.name
            self.service_id = False
            
    @api.onchange('service_id')
    def _onchange_service_id(self):
        super(SaleCreditProduct, self)._onchange_service_id()
        if self.service_id:
            self.property_id = False

    @api.constrains('product_type', 'property_id')
    def _check_product_consistency_property(self):
        for record in self:
            if record.product_type == 'property' and not record.property_id:
                raise ValidationError(_("Debe seleccionar una propiedad cuando el tipo es 'Propiedad'."))

class SaleCredit(models.Model):
    _inherit = 'sale.credit'
    
    contract_product_type = fields.Selection(selection_add=[
        ('property', 'Propiedad')
    ], ondelete={'property': 'cascade'}, default='property')
