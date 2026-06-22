# -*- coding: utf-8 -*-
"""
F1.5 - Ver Listado Cartera v1 (resumen) (QWeb PDF).

Equivalente a ``testarossa/modulos/cartera/class/ver_listado.php``
(293 lineas). Muestra el resumen de cartera de cobro agrupado por
Oficial de Cuenta (``sale.credit.oficial_id``).

Filtros disponibles:
    - company_id   (Compania)
    - date_from    (Fecha Desde - fecha_venta)
    - date_to      (Fecha Hasta - fecha_venta)
    - oficial_id   (Oficial de Cuenta, opcional)
    - motorista_id (Zona/Motorista, opcional)
    - estado_contrato (state selection, default 'active')

Salida: QWeb PDF con columnas:
    Oficial | #Contratos | Capital | Interes | Mora | Total

Mismo filtro con ``state='active'`` (excluye cerrados) por defecto.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VerListadoCarteraWizard(models.TransientModel):
    _name = "cjg.finance.ver.listado.cartera.wizard"
    _description = "F1.5 Ver Listado Cartera v1 (resumen)"

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
        """Construye el domain para filtrar ``sale.credit``."""
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

    def _get_credit_lines(self):
        """Devuelve ``sale.credit`` records filtrados, ordenados por oficial."""
        self.ensure_one()
        Credit = self.env["sale.credit"]
        return Credit.search(self._get_credit_domain(), order="oficial_id, name")

    def _get_payment_lines_domain(self, credits):
        """Domain de pagos (``sale.credit.payment``) para el filtro de fecha."""
        return [
            ("company_id", "=", self.company_id.id),
            ("state", "in", ["paid", "validated"]),
            ("payment_date", ">=", self.date_from),
            ("payment_date", "<=", self.date_to),
            ("credit_id", "in", credits.ids),
        ]

    def _aggregate_by_oficial(self, credits):
        """Agrupa contratos por oficial y suma capital/interes/mora.

        Retorna una lista de dicts con la estructura esperada por el
        template QWeb, ya ordenada por oficial.
        """
        self.ensure_one()
        PaymentLine = self.env["sale.credit.payment.line"]
        Payment = self.env["sale.credit.payment"]
        credit_lines_total = {}
        for credit in credits:
            key = credit.oficial_id.id if credit.oficial_id else 0
            entry = credit_lines_total.setdefault(key, {
                "oficial_id": credit.oficial_id.id,
                "oficial_name": credit.oficial_id.name or _("Sin Oficial"),
                "count": 0,
                "capital": 0.0,
                "interes": 0.0,
                "mora": 0.0,
            })
            entry["count"] += 1
            entry["capital"] += float(credit.amount_financed or 0.0)
            entry["interes"] += float(credit.amount_interest_value or 0.0)
            entry["mora"] += float(credit.total_charges or 0.0)
        if not credits:
            return []
        domain = self._get_payment_lines_domain(credits)
        payments = Payment.search(domain)
        if payments:
            plines = PaymentLine.search([
                ("sale_payment_id", "in", payments.ids),
            ])
            pay_by_credit = {}
            for pl in plines:
                cid = pl.sale_payment_id.credit_id.id
                pay_by_credit.setdefault(cid, {"capital": 0.0, "interest": 0.0, "overdue": 0.0})
                pay_by_credit[cid]["capital"] += float(pl.amount_capital or 0.0)
                pay_by_credit[cid]["interest"] += float(pl.amount_interest or 0.0)
                pay_by_credit[cid]["overdue"] += float(pl.amount_overdue or 0.0)
            for cid, vals in pay_by_credit.items():
                credit = credits.filtered(lambda c, cid=cid: c.id == cid)
                if not credit:
                    continue
                oficial = credit[:1].oficial_id
                key = oficial.id if oficial else 0
                if key in credit_lines_total:
                    credit_lines_total[key]["capital"] += vals["capital"]
                    credit_lines_total[key]["interes"] += vals["interest"]
                    credit_lines_total[key]["mora"] += vals["overdue"]
        rows = list(credit_lines_total.values())
        rows.sort(key=lambda r: r["oficial_name"] or "")
        for row in rows:
            row["total"] = (row["capital"] or 0.0) + (row["interes"] or 0.0) + (row["mora"] or 0.0)
        return rows

    def _build_report_data(self):
        """Prepara el diccionario ``data`` que consume el template QWeb."""
        self.ensure_one()
        credits = self._get_credit_lines()
        rows = self._aggregate_by_oficial(credits)
        totals = {
            "count": sum(r["count"] for r in rows),
            "capital": sum(r["capital"] for r in rows),
            "interes": sum(r["interes"] for r in rows),
            "mora": sum(r["mora"] for r in rows),
            "total": sum(r["total"] for r in rows),
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
        """Lanza el QWeb PDF definido en ``ver_listado_cartera_wizard.xml``."""
        self.ensure_one()
        data = self._build_report_data()
        return self.env.ref(
            "cjg_finance.action_report_ver_listado_cartera",
        ).report_action(self, data=data)
