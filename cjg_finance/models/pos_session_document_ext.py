from odoo import models, fields, api

class CjgPosSessionDocument(models.Model):
    _inherit = 'cjg.pos.session.document'

    credit_id = fields.Many2one("sale.credit", string="Credit")
    credit_line_id = fields.Many2one("sale.credit.line", string="Credit Installment")
    maintenance_contract_id = fields.Many2one("maintenance.contract", string="Maintenance Contract")

    # Expand selection
    document_type = fields.Selection(selection_add=[
        ("credit", "Credit Installment"),
        ("maintenance", "Maintenance Contract"),
    ], ondelete={'credit': 'cascade', 'maintenance': 'cascade'})

    @api.constrains("document_type", "credit_line_id", "maintenance_contract_id")
    def _check_document_link_finance(self):
        for doc in self:
            if doc.document_type == "credit" and not doc.credit_line_id:
                raise ValueError("A credit document must have an installment linked.")
            if doc.document_type == "maintenance" and not doc.maintenance_contract_id:
                raise ValueError("A maintenance document must have a contract linked.")
