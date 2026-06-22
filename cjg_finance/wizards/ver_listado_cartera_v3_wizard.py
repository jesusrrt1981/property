# -*- coding: utf-8 -*-
"""
F1.7 - Ver Listado Cartera v3 (con totales y subtotales por zona) (QWeb PDF).

Equivalente a ``testarossa/modulos/cartera/class/ver_listado_2.php``
(319 lineas). Igual que F1.5 (resumen por Oficial) pero incluye
totales globales y subtotales por Zona (motorista_id).

Filtros disponibles:
    - company_id   (Compania)
    - date_from    (Fecha Desde - fecha_venta)
    - date_to      (Fecha Hasta - fecha_venta)
    - oficial_id   (Oficial de Cuenta, opcional)
    - motorista_id (Zona/Motorista, opcional)
    - estado_contrato (state selection, default 'active')

Salida: QWeb PDF con agrupacion por Oficial y subtotal por Zona + total
general al pie.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class VerListadoCarteraV3Wizard(models.TransientModel):
    _name = "cjg.finance.ver.listado.cartera.v3.wizard"
    _description = "F1.7 Ver Listado Cartera v3 (con totales)"

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

    def _aggregate(self, credits):
        """Agrupa contratos en (Oficial, Zona) y calcula subtotales.

        Estructura retornada (lista):
            [
                {
                    'oficial_id', 'oficial_name',
                    'zonas': [
                        {'zona_id', 'zona_name',
                         'count', 'capital', 'interes', 'mora', 'total'}
                    ],
                    'count', 'capital', 'interes', 'mora', 'total',
                }
            ]
        """
        self.ensure_one()
        grouped = {}
        for credit in credits:
            of_id = credit.oficial_id.id if credit.oficial_id else 0
            of_name = credit.oficial_id.name or _("Sin Oficial")
            zn_id = credit.motorista_id.id if credit.motorista_id else 0
            zn_name = credit.motorista_id.name or _("Sin Zona")
            oficial = grouped.setdefault(of_id, {
                "oficial_id": of_id,
                "oficial_name": of_name,
                "zonas": {},
                "count": 0,
                "capital": 0.0,
                "interes": 0.0,
                "mora": 0.0,
            })
            zona = oficial["zonas"].setdefault(zn_id, {
                "zona_id": zn_id,
                "zona_name": zn_name,
                "count": 0,
                "capital": 0.0,
                "interes": 0.0,
                "mora": 0.0,
            })
            zona["count"] += 1
            zona["capital"] += float(credit.amount_financed or 0.0)
            zona["interes"] += float(credit.amount_interest_value or 0.0)
            zona["mora"] += float(credit.total_charges or 0.0)
            oficial["count"] += 1
            oficial["capital"] += float(credit.amount_financed or 0.0)
            oficial["interes"] += float(credit.amount_interest_value or 0.0)
            oficial["mora"] += float(credit.total_charges or 0.0)

        result = []
        for of_id, of in sorted(
            grouped.items(), key=lambda kv: kv[1]["oficial_name"] or "",
        ):
            zonas = []
            for zn_id, zn in sorted(
                of["zonas"].items(), key=lambda kv: kv[1]["zona_name"] or "",
            ):
                zn["total"] = (zn["capital"] or 0.0) + (zn["interes"] or 0.0) + (zn["mora"] or 0.0)
                zonas.append(zn)
            of["zonas_list"] = zonas
            of["total"] = (of["capital"] or 0.0) + (of["interes"] or 0.0) + (of["mora"] or 0.0)
            result.append(of)
        return result

    def _build_report_data(self):
        self.ensure_one()
        Credit = self.env["sale.credit"]
        credits = Credit.search(self._get_credit_domain(), order="oficial_id, motorista_id, name")
        groups = self._aggregate(credits)
        totals = {
            "count": sum(g["count"] for g in groups),
            "capital": sum(g["capital"] for g in groups),
            "interes": sum(g["interes"] for g in groups),
            "mora": sum(g["mora"] for g in groups),
            "total": sum(g["total"] for g in groups),
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
            "groups": groups,
            "totals": totals,
        }

    def action_print_report(self):
        self.ensure_one()
        data = self._build_report_data()
        return self.env.ref(
            "cjg_finance.action_report_ver_listado_cartera_v3",
        ).report_action(self, data=data)
