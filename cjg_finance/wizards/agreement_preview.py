import re

from odoo import api, fields, models


class AgreementPreview(models.TransientModel):
    _name = "agreement.preview"
    _description = "Agreement Preview"

    agreement_id = fields.Many2one("agreement.template", string="Plantilla")
    body = fields.Html(string="Vista Previa", compute="_compute_preview")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self._context.get("active_id")
        res["agreement_id"] = active_id
        return res

    @api.depends("agreement_id")
    def _compute_preview(self):
        for rec in self:
            if rec.agreement_id.template_variable_ids:
                body = rec.agreement_id.agreement
                variable_dict = {}
                body_var = set(re.findall(r"{{[1-9][0-9]*}}", body or ""))
                for var in rec.agreement_id.template_variable_ids:
                    variable_dict[var.name] = var.demo or ""
                for data in body_var:
                    body = body.replace(data, variable_dict.get(data, ""))
                rec.body = body
            else:
                rec.body = ""
