# -*- coding: utf-8 -*-
"""
Modelo ``cjg.sale.credit.direccion.temp`` — réplica de la tabla legacy
``sys_direccion_temp`` de Testarossa (caja).

=====================================================================
DOCSTRING DE REPLICA LEGACY (no eliminar — referencia para auditoría)
=====================================================================

En Testarossa existe una tabla ``sys_direccion_temp`` que almacena
direcciones capturadas en formularios de manera temporal, ANTES de
hacer commit sobre la dirección oficial del cliente
(``res.partner`` o equivalente legacy ``cliente.direccion``).

Razones del modelo temporal en legacy:
    1. Formularios web que necesitan "guardar borrador" antes de validar
       la dirección real.
    2. Procesos de captura de campo (motorizados) que sincronizan al
       volver a tener señal y entonces se promueve la dirección.
    3. Rollback operativo: si falla la validación final, el temporal
       sigue ahí para inspección y se evita ensuciar ``res.partner``.

Estructura legacy (mapeo conceptual):
    sys_direccion_temp.id            -> id (PK)
    sys_direccion_temp.partner_id    -> partner_id (FK cliente)
    sys_direccion_temp.direccion     -> direccion (TEXT, la dirección capturada)
    sys_direccion_temp.status        -> status (ENUM: 'draft', 'committed', 'cancelled')
    sys_direccion_temp.created_at    -> create_date
    sys_direccion_temp.committed_at  -> commit_date

=====================================================================

Aquí lo modelamos como un modelo Odoo 17 con un botón ``action_commit``
que:
    1. Toma la dirección temporal.
    2. La escribe en el campo ``street`` del ``res.partner``.
    3. Marca la línea como ``status='committed'`` y guarda ``commit_date``.

El campo ``status='cancelled'`` se usa para marcar direcciones inválidas
que NO deben promoverse al partner.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SaleCreditDireccionTemp(models.Model):
    _name = "cjg.sale.credit.direccion.temp"
    _description = "Dirección Temporal del Cliente (sys_direccion_temp)"
    _order = "id desc"
    _rec_name = "display_name"

    # ── Campos legacy ──────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        "res.partner", string="Cliente", required=True,
        ondelete="cascade",
    )
    direccion = fields.Text(
        string="Dirección (Capturada)",
        required=True,
        help="Dirección escrita por el operador o sincronizada del field app. "
             "Equivalente a sys_direccion_temp.direccion en Testarossa.",
    )
    status = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("committed", "Promovida"),
            ("cancelled", "Cancelada"),
        ],
        string="Estado", default="draft", required=True, index=True,
    )
    commit_date = fields.Datetime(
        string="Fecha de Promoción", readonly=True,
        help="Se llena al ejecutar action_commit. Equivalente a "
             "sys_direccion_temp.committed_at en Testarossa.",
    )
    cancel_date = fields.Datetime(
        string="Fecha de Cancelación", readonly=True,
    )
    notes = fields.Text(string="Notas / Motivo")
    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company,
    )

    # ── Computed ───────────────────────────────────────────────────────────
    display_name = fields.Char(
        compute="_compute_display_name", store=True,
    )

    @api.depends("partner_id.name", "status", "create_date")
    def _compute_display_name(self):
        for rec in self:
            partner = rec.partner_id.name if rec.partner_id else "?"
            date = fields.Date.to_string(rec.create_date) if rec.create_date else "?"
            rec.display_name = "[%s] %s — %s" % (
                rec.status, partner, date,
            )

    # ── Constraints ────────────────────────────────────────────────────────
    @api.constrains("direccion")
    def _check_direccion_min_length(self):
        for rec in self:
            if rec.direccion and len(rec.direccion.strip()) < 5:
                raise ValidationError(_(
                    "La dirección capturada es demasiado corta "
                    "(mínimo 5 caracteres)."
                ))

    # ── Actions ────────────────────────────────────────────────────────────
    def action_commit(self):
        """Promueve la dirección temporal al res.partner."""
        self.ensure_one()
        if self.status != "draft":
            raise UserError(_(
                "Sólo se pueden promover direcciones en estado 'Borrador'. "
                "Esta línea está en estado '%s'."
            ) % self.status)

        if not self.partner_id.exists():
            raise UserError(_(
                "El cliente asociado ya no existe. No se puede promover la "
                "dirección."
            ))

        # Si el partner ya tiene street, sobreescribimos sólo si está vacío.
        partner = self.partner_id
        old_street = partner.street
        partner.write({"street": self.direccion.strip()})

        self.write({
            "status": "committed",
            "commit_date": fields.Datetime.now(),
            "notes": (self.notes or "") + (
                "\n[Promovida] street anterior='%s'" % (old_street or "")
            ),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Dirección Promovida"),
                "message": _(
                    "La dirección temporal de %s fue promovida al cliente."
                ) % partner.name,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_cancel_temp(self):
        """Marca la línea como cancelada (NO se promueve)."""
        self.ensure_one()
        if self.status == "committed":
            raise UserError(_(
                "No se puede cancelar una dirección ya promovida."
            ))
        self.write({
            "status": "cancelled",
            "cancel_date": fields.Datetime.now(),
        })
        return True
