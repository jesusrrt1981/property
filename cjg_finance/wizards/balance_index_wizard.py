# -*- coding: utf-8 -*-
"""
F1.4 — Pantalla Index de Balance (router/wizard sin datos).

Equivalente a ``testarossa/modulos/balance/view/view_index.php``
(1.123 líneas). En Odoo esto se modela como:

    - Una vista form (no es un wizard real porque no recolecta
      datos: solo es un hub de navegación con 3 botones).
    - Cada botón abre uno de los 3 wizards anteriores mediante
      ``type="action"``.

La "pantalla" se implementa como transient model
``cjg.finance.balance.index`` para poder registrarle una
vista form y un menú propio, sin necesidad de un componente
JS custom.
"""
from odoo import api, fields, models


class BalanceIndexRouter(models.TransientModel):
    _name = "cjg.finance.balance.index"
    _description = "Index de Balance (Hub de Wizards)"

    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(string="Fecha Desde")
    date_to = fields.Date(string="Fecha Hasta")

    def action_open_cuenta(self):
        """Abre el wizard de Cuenta Corriente."""
        self.ensure_one()
        action = self.env.ref(
            "cjg_finance.action_balance_cuenta_wizard"
        ).read()[0]
        action['context'] = {
            'default_company_id': self.company_id.id,
            'default_date_from': self.date_from or fields.Date.today(),
            'default_date_to': self.date_to or fields.Date.today(),
        }
        return action

    def action_open_global(self):
        """Abre el wizard de Balance Global (XLSX)."""
        self.ensure_one()
        action = self.env.ref(
            "cjg_finance.action_balance_global_wizard"
        ).read()[0]
        action['context'] = {
            'default_company_id': self.company_id.id,
            'default_date_from': self.date_from or fields.Date.today(),
            'default_date_to': self.date_to or fields.Date.today(),
        }
        return action

    def action_open_movimiento(self):
        """Abre el wizard de Movimiento por Oficial (XLSX)."""
        self.ensure_one()
        action = self.env.ref(
            "cjg_finance.action_balance_movimiento_wizard"
        ).read()[0]
        action['context'] = {
            'default_company_id': self.company_id.id,
            'default_date_from': self.date_from or fields.Date.today(),
            'default_date_to': self.date_to or fields.Date.today(),
        }
        return action
