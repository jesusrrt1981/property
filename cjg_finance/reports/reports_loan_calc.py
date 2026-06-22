from odoo import models, api

class ReportLoanCalc(models.AbstractModel):
    _name = 'report.cjg_finance.report_loan_calc'
    _description = 'Reporte de Calculadora de Préstamos'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['loan.calc'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'loan.calc',
            'docs': docs,
        }
