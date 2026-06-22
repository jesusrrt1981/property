# -*- coding: utf-8 -*-
"""
Wizard para Listado de Abonos Iniciales del Cliente (QWeb PDF).

Equivalente a ``listado_abono_inicial.php`` de Testarossa
(caja/view/cliente/, 99 líneas). El legacy filtra movimientos tipo
'inicial' para un partner dado y muestra:

  Fecha, Docto, TC (tipo de cambio), Tipo Doc, Serie, No. Doc, Monto

Aquí lo modelamos como un wizard TransientModel que recibe un
``partner_id`` y delega al modelo ``cjg.pos.payment.receipt`` filtrando
por ``movement_type='ini'`` (Pago Inicial).
"""
from odoo import api, fields, models, _


class PartnerInitialPaymentsWizard(models.TransientModel):
    _name = "cjg.finance.partner.initial.payments.wizard"
    _description = "Listado de Abonos Iniciales del Cliente"

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
        """Retorna los recibos con tipo de movimiento 'ini' del partner."""
        domain = [
            ("partner_id", "=", self.partner_id.id),
            ("movement_type", "=", "ini"),
            ("state", "!=", "cancelled"),
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
            "cjg_finance.action_report_partner_initial_payments",
        ).report_action(self, data={
            "wizard_id": self.id,
            "receipt_ids": receipts.ids,
            "partner_id": self.partner_id.id,
            "date_from": str(self.date_from) if self.date_from else False,
            "date_to": str(self.date_to) if self.date_to else False,
        })
