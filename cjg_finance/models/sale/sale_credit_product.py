from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaleCreditProduct(models.Model):
    _name = 'sale.credit.product'
    _description = 'Productos del Contrato'
    
    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        ondelete='cascade'
    )
    
    product_type = fields.Selection([
        ('service', 'Servicio'),
        # 'property' option added by cjg_finance_property module via selection_add
    ], string='Tipo de Producto', required=True)
    
    # Para Servicios
    service_id = fields.Many2one(
        'product.template',
        string='Servicio',
        domain="[('is_funeral_product', '=', True), ('type', '=', 'service')]"
    )

    # property_id moved to cjg_finance_property module to avoid dependency on property.details model
    # This prevents circular dependency issues when property module is not installed
    
    description = fields.Char(string='Descripción')
    
    price = fields.Float(string='Precio', required=True, default=0.0)
    
    @api.onchange('service_id')
    def _onchange_service_id(self):
        if self.service_id:
            self.product_type = 'service'
            self.price = self.service_id.lst_price
            self.description = self.service_id.name


    @api.constrains('product_type', 'service_id')
    def _check_product_consistency(self):
        for record in self:
            if record.product_type == 'service' and not record.service_id:
                raise ValidationError(_("Debe seleccionar un servicio cuando el tipo es 'Servicio'."))
            # property validation moved to cjg_finance_property module
            # Validar consistencia con el contrato padre
            if record.credit_id.contract_product_type and record.credit_id.contract_product_type != record.product_type:
                raise ValidationError(_(
                    "No puede mezclar tipos de productos. El contrato está configurado como '%s' pero intenta agregar un '%s'."
                ) % (dict(record.credit_id._fields['contract_product_type'].selection).get(record.credit_id.contract_product_type), 
                     dict(record._fields['product_type'].selection).get(record.product_type)))
