# -*- coding: utf-8 -*-
"""
F1.1 — Plantilla Cuenta Corriente (QWeb HTML).

Equivalente a ``testarossa/modulos/balance/view/plantilla_cuenta.php``
(491 líneas). Muestra para un cliente/partner el detalle cronológico
de sus movimientos de recibo (debe/haber) en un rango de fechas, con:

    - Saldo inicial: suma de movimientos hasta date_from - 1
    - Movimientos del periodo (fecha, docto, descripción, debe, haber)
    - Saldo corrido línea a línea
    - Saldo final: saldo_inicial + debe - haber

Genera un PDF QWeb con cabecera de compañía y datos del cliente.
"""
from odoo import api, fields, models


class BalanceCuentaWizard(models.TransientModel):
    _name = "cjg.finance.balance.cuenta.wizard"
    _description = "Plantilla Cuenta Corriente (CxC)"

    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Cliente", required=True,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)

    def _get_initial_balance(self):
        """Saldo anterior: suma de amount_paid de todos los recibos
        del partner con fecha < date_from y estado != cancelled."""
        self.ensure_one()
        domain = [
            ("partner_id", "=", self.partner_id.id),
            ("state", "!=", "cancelled"),
            ("date", "<", self.date_from),
        ]
        if self.company_id:
            domain.append(("company_id", "=", self.company_id.id))
        receipts = self.env["cjg.pos.payment.receipt"].search(domain)
        return sum(receipts.mapped("amount_paid")), len(receipts)

    def _get_period_movements(self):
        """Movimientos del periodo, ordenados cronológicamente."""
        self.ensure_one()
        domain = [
            ("partner_id", "=", self.partner_id.id),
            ("state", "!=", "cancelled"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ]
        if self.company_id:
            domain.append(("company_id", "=", self.company_id.id))
        return self.env["cjg.pos.payment.receipt"].search(
            domain, order="date asc, name asc",
        )

    def action_print_report(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            from odoo.exceptions import UserError
            from odoo.tools.translate import _
            raise UserError(_(
                "La fecha desde debe ser anterior o igual a la fecha hasta."
            ))
        initial_balance, _ = self._get_initial_balance()
        movements = self._get_period_movements()
        return self.env.ref(
            "cjg_finance.action_report_balance_cuenta",
        ).report_action(self, data={
            "wizard_id": self.id,
            "partner_id": self.partner_id.id,
            "date_from": str(self.date_from),
            "date_to": str(self.date_to),
            "initial_balance": initial_balance,
            "movement_ids": movements.ids,
        })
