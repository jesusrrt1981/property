# -*- coding: utf-8 -*-
"""
F1.8 - Ver Listado Saldos (con totales) (QWeb PDF).

Equivalente a ``testarossa/modulos/cartera/class/ver_listado_saldos.php``
(357 lineas). Saldos por cliente con totales globales.

12 columnas (legacy):
    1.  Cedula
    2.  Cliente
    3.  Capital
    4.  Interes
    5.  Mora
    6.  Cuotas Vencidas
    7.  Saldo Total
    8.  Saldo Pagado
    9.  Saldo Pendiente
    10. Estado
    11. Oficial
    12. Fecha Ultimo Pago

Filtros disponibles:
    - company_id   (Compania)
    - date_from    (Fecha Desde - fecha_venta)
    - date_to      (Fecha Hasta - fecha_venta)
    - oficial_id   (Oficial de Cuenta, opcional)
    - motorista_id (Zona/Motorista, opcional)
    - estado_contrato (state selection, default 'active')
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VerListadoSaldosWizard(models.TransientModel):
    _name = "cjg.finance.ver.listado.saldos.wizard"
    _description = "F1.8 Ver Listado Saldos (con totales)"

    company_id = fields.Many2one(
        "res.company", string="Compania",
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)
    oficial_id = fields.Many2one(
        "res.users", string="Oficial de Cuenta",
        domain=[("share", "=", False)],
    )
    motorista_id = fields.Many2one(
        "res.partner", string="Zona / Motorista",
        domain=[("is_motorista", "=", True)],
    )
    estado_contrato = fields.Selection(
        selection=[
            ("active", "Activo"),
            ("approved", "Aprobado"),
            ("withdrawing", "Por Desistir"),
            ("legal", "En Legal"),
            ("all_except_closed", "Todos (excluye Cerrados)"),
        ],
        string="Estado Contrato",
        default="active",
        required=True,
    )

    def _get_credit_domain(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_(
                "La fecha desde debe ser anterior o igual a la fecha hasta."
            ))
        domain = [
            ("company_id", "=", self.company_id.id),
            ("date_contract", ">=", self.date_from),
            ("date_contract", "<=", self.date_to),
        ]
        if self.estado_contrato == "all_except_closed":
            domain.append(("state", "not in", ["closed", "cancelled", "refuse"]))
        else:
            domain.append(("state", "=", self.estado_contrato))
        if self.oficial_id:
            domain.append(("oficial_id", "=", self.oficial_id.id))
        if self.motorista_id:
            domain.append(("motorista_id", "=", self.motorista_id.id))
        return domain

    def _compute_saldos_for_credit(self, credit, cutoff):
        """Calcula los 12 valores de la fila legacy para un contrato.

        Retorna un dict con claves:
            cedula, cliente, capital, interes, mora, cuotas_vencidas,
            saldo_total, saldo_pagado, saldo_pendiente, estado,
            oficial, fecha_ultimo_pago
        """
        self.ensure_one()
        cedula = credit.partner_id.vat or ''
        cliente = credit.partner_id.name or ''
        capital = float(credit.amount_financed or 0.0)
        interes = float(credit.amount_interest_value or 0.0)
        mora = float(credit.total_charges or 0.0)
        saldo_total = capital + interes + mora

        lines = credit.credit_lines.filtered(
            lambda l: l.expected_date_payment and l.expected_date_payment < cutoff
        )
        cuotas_vencidas = len(lines.filtered(
            lambda l: l.state in ('pending', 'paid_overdue', 'paid_reload')
        ))

        paid_lines = credit.credit_lines.filtered(
            lambda l: l.state == 'paid'
        )
        saldo_pagado = sum(paid_lines.mapped('amount_paid_total'))

        saldo_pendiente = max(saldo_total - saldo_pagado, 0.0)

        estado_label = dict(credit._fields['state'].selection).get(
            credit.state, credit.state,
        )

        # SPRINT COBROS-CRITICOS 2026-06-20 Fix #3h: helper unificado
        # en display de listado de saldos.
        if hasattr(credit, '_get_collection_officer'):
            officer = credit._get_collection_officer()
        else:
            officer = credit.oficial_id or credit.collection_user_id
        oficial_name = officer.name if officer else ''

        last_payment = self.env["sale.credit.payment"].search([
            ("credit_id", "=", credit.id),
            ("state", "in", ["paid", "validated"]),
        ], order="payment_date desc", limit=1)
        fecha_ultimo_pago = (
            fields.Date.to_string(last_payment.payment_date)
            if last_payment and last_payment.payment_date else ''
        )

        return {
            "cedula": cedula,
            "cliente": cliente,
            "capital": capital,
            "interes": interes,
            "mora": mora,
            "cuotas_vencidas": cuotas_vencidas,
            "saldo_total": saldo_total,
            "saldo_pagado": saldo_pagado,
            "saldo_pendiente": saldo_pendiente,
            "estado": estado_label,
            "oficial": oficial_name,
            "fecha_ultimo_pago": fecha_ultimo_pago,
        }

    def _build_report_data(self):
        self.ensure_one()
        Credit = self.env["sale.credit"]
        credits = Credit.search(
            self._get_credit_domain(),
            order="oficial_id, partner_id, name",
        )
        cutoff = self.date_to
        rows = [self._compute_saldos_for_credit(c, cutoff) for c in credits]
        totals = {
            "capital": sum(r["capital"] for r in rows),
            "interes": sum(r["interes"] for r in rows),
            "mora": sum(r["mora"] for r in rows),
            "cuotas_vencidas": sum(r["cuotas_vencidas"] for r in rows),
            "saldo_total": sum(r["saldo_total"] for r in rows),
            "saldo_pagado": sum(r["saldo_pagado"] for r in rows),
            "saldo_pendiente": sum(r["saldo_pendiente"] for r in rows),
            "count": len(rows),
        }
        return {
            "wizard_id": self.id,
            "company_name": self.company_id.name,
            "date_from": fields.Date.to_string(self.date_from),
            "date_to": fields.Date.to_string(self.date_to),
            "estado_contrato": dict(self._fields["estado_contrato"].selection).get(
                self.estado_contrato, self.estado_contrato,
            ),
            "oficial_name": self.oficial_id.name or _("Todos"),
            "zona_name": self.motorista_id.name or _("Todas"),
            "rows": rows,
            "totals": totals,
        }

    def action_print_report(self):
        self.ensure_one()
        data = self._build_report_data()
        return self.env.ref(
            "cjg_finance.action_report_ver_listado_saldos",
        ).report_action(self, data=data)
