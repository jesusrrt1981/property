from odoo import models, fields, api


class ReportInvoiceWithoutCreditPayment(models.AbstractModel):
    _name = 'report.cjg_finance.report_sale_credit'
    # _inherit ='sale.credit.payment'
    _description = 'Account report without payment lines'

    @api.model
    def _get_report_values(self, docids, data=None):
        report_obj=self.env['ir.actions.report']
        report=report_obj._get_report_from_name('odoo_qweb.report_form')
        docs = self.env['sale.credit.payment'].browse(docids)


        return {
            'doc_ids': docids,
            'doc_model': 'sale.credit.payment',
            'docs':docs
        }