import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    credit_line_id = fields.Many2one(
        "sale.credit.line",
        readonly=True,
        ondelete="restrict",
    )
    credit_id = fields.Many2one(
        "sale.credit",
        readonly=True,
        store=True,
        ondelete="restrict",
    )
    def action_post(self):
        res = super().action_post()

        for invoice in self:
            try:
                with self.env.cr.savepoint():
                    self.env['credit.overdue'].update_credit_overdue_status(invoice)
            except Exception:
                _logger.exception('Failed to sync overdue for invoice %s', invoice.id)
                # No relanzar: la factura ya está posteada, no revertir

        return res

    # def action_post(self):
    #     res = super().action_post()
    #     # for record in self:
    #     #     loan_line_id = record.loan_line_id
    #     #     if loan_line_id:
    #     #         if not record.loan_line_id:
    #     #             record.loan_line_id = loan_line_id
    #     #         record.loan_id = loan_line_id.loan_id
    #     #         record.loan_line_id.check_move_amount()
    #     #         record.loan_line_id.loan_id.compute_posted_lines()
    #     #         if record.loan_line_id.sequence == record.loan_id.periods:
    #     #             record.loan_id.close()
    #     return res