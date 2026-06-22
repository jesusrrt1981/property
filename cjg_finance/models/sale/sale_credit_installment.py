from odoo import models, fields, api

class SaleCreditInstallment(models.Model):
    _name = "sale.credit.installment"
    _description = "Cuotas"
    _order = "installments asc"

    name = fields.Char(string="Nombre", required=True)
    installments = fields.Integer(string="Cuotas", required=True)
    
    _sql_constraints = [
        ('install_unique', 'unique (installments)',
            'El numero de Cuotas son unicas')
    ]

    @api.model
    def _ensure_standard_installments(self):
        installments_to_ensure = [
            ("8_cuota", 8, "8 Cuotas"),
            ("12_cuota", 12, "12 Cuotas"),
            ("24_cuota", 24, "24 Cuotas"),
            ("36_cuota", 36, "36 Cuotas"),
            ("48_cuota", 48, "48 Cuotas"),
            ("60_cuota", 60, "60 Cuotas"),
            ("72_cuota", 72, "72 Cuotas"),
            ("84_cuota", 84, "84 Cuotas"),
        ]

        imd = self.env["ir.model.data"].sudo()
        for xmlid_name, number, display_name in installments_to_ensure:
            xmlid_row = imd.search(
                [("module", "=", "cjg_finance"), ("name", "=", xmlid_name)], limit=1
            )
            record = False
            if xmlid_row and xmlid_row.model == self._name and xmlid_row.res_id:
                record = self.browse(xmlid_row.res_id).exists()

            if not record:
                record = self.search([("installments", "=", number)], limit=1)

            if record:
                values = {}
                if record.installments != number:
                    values["installments"] = number
                if display_name and record.name != display_name:
                    values["name"] = display_name
                if values:
                    record.write(values)
            else:
                record = self.create({"name": display_name, "installments": number})

            if xmlid_row:
                xmlid_row.write({"model": self._name, "res_id": record.id})
            else:
                imd.create(
                    {
                        "module": "cjg_finance",
                        "name": xmlid_name,
                        "model": self._name,
                        "res_id": record.id,
                    }
                )

    @api.model
    def _ensure_funeral_installments(self):
        installments_to_ensure = [
            ("72_cuota", 72, "72 Cuotas"),
            ("84_cuota", 84, "84 Cuotas"),
        ]

        imd = self.env["ir.model.data"].sudo()
        for xmlid_name, number, display_name in installments_to_ensure:
            xmlid_row = imd.search(
                [("module", "=", "cjg_finance"), ("name", "=", xmlid_name)], limit=1
            )
            record = False
            if xmlid_row and xmlid_row.model == self._name and xmlid_row.res_id:
                record = self.browse(xmlid_row.res_id).exists()

            if not record:
                record = self.search([("installments", "=", number)], limit=1)

            if record:
                values = {}
                if record.installments != number:
                    values["installments"] = number
                if display_name and record.name != display_name:
                    values["name"] = display_name
                if values:
                    record.write(values)
            else:
                record = self.create({"name": display_name, "installments": number})

            if xmlid_row:
                xmlid_row.write({"model": self._name, "res_id": record.id})
            else:
                imd.create(
                    {
                        "module": "cjg_finance",
                        "name": xmlid_name,
                        "model": self._name,
                        "res_id": record.id,
                    }
                )
