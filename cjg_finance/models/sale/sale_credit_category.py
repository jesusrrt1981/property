from odoo import models, fields, api


class SaleCreditCategory(models.Model):
    _name = "sale.credit.category"
    _description = "Categoría"

    name = fields.Char(string="Nombre", required=True)
    description = fields.Text(string="Descripción")
    percent_interest = fields.Float(string="Interés(%)")
    percent_financing = fields.Float(string="Finaciado(%)")
    company_id = fields.Many2one(
        'res.company', 'Company', required=True, default=lambda self: self.env.company)
    journal_id = fields.Many2one(
        'account.journal',
        string="Diario Prestamos",
        domain="[('type', 'in', ('sale', 'general'))]",
        default=lambda self: self.env.company.credit_journal_id)
    
    use_credit = fields.Boolean("Utilizar Verificacion de Credito?")
    is_doc_required = fields.Boolean("Documentos Requerido?")
    is_extra_invocing = fields.Boolean("Generar Factura Mora e Intereses?", default=True)
    sale_credit_doc_ids = fields.Many2many(
        'sale.credit.document',
        'sale_credit_category_id',
        'sale_credit_doc_id',
        string='Documentos',
    )
    
    credit_account_receivable_id = fields.Many2one(
        'account.account',
        string="Cuenta por Cobrar",
        domain="[('deprecated', '=', False), ('account_type', '=', 'asset_receivable'), ('company_id', '=', current_company_id)]",
        default=lambda self: self.env.company.credit_account_receivable_id)
    
    credit_account_advanced_id = fields.Many2one(
        'account.account',
        string="Cuenta de Avance Cliente",
        domain="[('deprecated', '=', False), ('account_type', '=', 'liability_payable'), ('company_id', '=', current_company_id)]",
        default=lambda self: self.env.company.credit_account_advanced_id)
    
    credit_earning_id = fields.Many2one(
        'account.account',
        string="Cuenta de Ingreso",
        domain="[('deprecated', '=', False)]",
        default=lambda self: self.env.company.credit_earning_id)
    
class SaleCreditDocument(models.Model):
    _name = 'sale.credit.document'
    _description = 'Sale Credit Documents'

    name = fields.Char("Name", required=True)
