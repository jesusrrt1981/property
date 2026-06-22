# -*- coding: utf-8 -*-
"""
Wizard para Listado de Abonos del Cliente sin Inicial (QWeb PDF).

Equivalente a ``listado_abonos_cliente.php`` de Testarossa
(caja/view/cliente/, 58 líneas). Mismo concepto que el listado de
abonos iniciales pero excluyendo el movimiento ``ini``.

Columnas: Fecha, Docto, TC, Serie, No. Doc, Monto, Caja.
"""
from odoo import api, fields, models


class PartnerPaymentsWizard(models.TransientModel):
    _name = "cjg.finance.partner.payments.wizard"
    _description = "Listado de Abonos del Cliente (sin Inicial)"

    partner_id = fields.Many2one(
        "res.partner", string="Cliente", required=True,
    )
    date_from = fields.Date(string="Fecha Desde")
    date_to = fields.Date(string="Fecha Hasta")
    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company,
    )

    def _get_receipts(self):
        """Retorna los recibos del partner, excluyendo movement_type='ini'."""
        domain = [
            ("partner_id", "=", self.partner_id.id),
            ("state", "!=", "cancelled"),
            ("movement_type", "!=", "ini"),
        ]
        if self.date_from:
            domain.append(("date", ">=", self.date_from))
        if self.date_to:
            domain.append(("date", "<=", self.date_to))
        if self.company_id:
            domain.append(("company_id", "=", self.company_id.id))
        return self.env["cjg.pos.payment.receipt"].search(
            domain, order="date asc, name asc",
        )

    def action_print_report(self):
        self.ensure_one()
        receipts = self._get_receipts()
        return self.env.ref(
            "cjg_finance.action_report_partner_payments",
        ).report_action(self, data={
            "wizard_id": self.id,
            "receipt_ids": receipts.ids,
            "partner_id": self.partner_id.id,
            "date_from": str(self.date_from) if self.date_from else False,
            "date_to": str(self.date_to) if self.date_to else False,
        })
