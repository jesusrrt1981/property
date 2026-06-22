import re
from datetime import date, datetime

from odoo import api, fields, models


class AgreementTemplate(models.Model):
    _name = "agreement.template"
    _description = "Agreement Template"

    name = fields.Char(string="Título", translate=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
    )
    agreement = fields.Html(string="Contrato")
    template_variable_ids = fields.One2many(
        "agreement.template.variables",
        "template_id",
        compute="_compute_agreement_variable_ids",
        store=True,
        precompute=True,
        readonly=False,
        copy=False,
        string="Variables",
    )
    model = fields.Char(string="Modelo Relacionado")

    @api.depends("agreement")
    def _compute_agreement_variable_ids(self):
        """Mantiene sincronizadas las variables con los placeholders {{1}}, {{2}}, etc."""
        for rec in self:
            delete_var = self.env["agreement.template.variables"]
            created_var = []
            body_var = set(re.findall(r"{{[1-9][0-9]*}}", rec.agreement or ""))
            existing_var = rec.template_variable_ids
            new_var = [
                var_name
                for var_name in body_var
                if var_name not in existing_var.mapped("name")
            ]
            deleted_var = existing_var.filtered(lambda var: var.name not in body_var)
            created_var += [{"name": var_name} for var_name in set(new_var)]
            delete_var += deleted_var
            rec.template_variable_ids = [
                (3, to_remove.id) for to_remove in delete_var
            ] + [(0, 0, vals) for vals in created_var]

    def _format_value(self, value):
        """Normaliza valores para merge/preview."""
        if value is False or value is None:
            return ""
        if isinstance(value, models.Model):
            if len(value) > 1:
                return ", ".join(value.mapped("display_name"))
            return value.display_name
        if isinstance(value, (date, datetime)):
            # usa formato de contexto del usuario
            lang = self.env.lang or "es_DO"
            lang_date_format = self.env["res.lang"]._lang_get(lang).date_format
            return value.strftime(lang_date_format)
        return str(value)

    def _get_field_value(self, record, field_path):
        """Permite path tipo partner_id.phone o company_id.country_id.name."""
        current = record
        for part in (field_path or "").split("."):
            if not current:
                return ""
            current = getattr(current, part, False)
        return self._format_value(current)

    def build_variables_dict(self, record):
        """Devuelve dict {placeholder: valor} según template_variable_ids."""
        self.ensure_one()
        values = {}
        for var in self.template_variable_ids:
            if var.field_type == "free_text":
                values[var.name] = var.free_text or ""
            elif var.field_type == "field" and var.field_name:
                values[var.name] = self._get_field_value(record, var.field_name)
            else:
                values[var.name] = ""
        return values


class AgreementTemplateVariable(models.Model):
    _name = "agreement.template.variables"
    _description = "Agreement Variable Templates"
    _order = "name"

    template_id = fields.Many2one("agreement.template", string="Plantilla de Contrato")
    name = fields.Char(string="Placeholder")
    model = fields.Char(related="template_id.model", string="Modelo", store=True)
    field_type = fields.Selection(
        [("free_text", "Texto Libre"), ("field", "Campo del Modelo")],
        string="Tipo",
        default="free_text",
    )
    field_name = fields.Char(string="Campo Relacionado")
    demo = fields.Char(string="Valor de Prueba", default="Demo Value")
    free_text = fields.Char(string="Valor Libre")
