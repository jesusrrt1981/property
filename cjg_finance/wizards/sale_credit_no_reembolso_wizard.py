# -*- coding: utf-8 -*-
"""
Wizard: No Solicitar Reembolso (Solicitud Escrita).

Replica el procedimiento del documento 'Proceso reactivacion y Mejora'
(parrafos 23 y 180): cuando el cliente decide NO solicitar reembolso ni
nota de credito, se registra la solicitud por escrito (motivo + fecha +
autorizador) y el monto pagado queda en los ingresos de la empresa.

Adaptaciones aplicadas al esquema real del modulo:

  * El modelo ``sale.credit`` ya expone los campos
    ``no_refund_registered`` / ``no_refund_date`` / ``no_refund_user_id``
    (definidos en el bloque "CAMPOS NO REEMBOLSO (OPCION 2)"). Este
    wizard REUTILIZA esos campos — NO crea campos paralelos con nombre
    ``no_reembolso_*`` — para mantener una sola fuente de verdad y
    compatibilidad con el badge "Sin Reembolso Registrado" de la vista
    ``sale_credit_process_views.xml`` y con el metodo
    ``action_register_no_refund``.

  * ``paid_capital`` NO esta almacenado en ``sale.credit``. Se computa
    en el propio wizard a partir de ``amount_total`` y ``credit_Adeudado``
    (mismo patron que ``sale_credit_reembolso_wizard``).

  * El grupo de Documentacion (``cjg_finance.group_documentation_user``
    / ``cjg_finance.group_documentation_manager``) se reutiliza para
    el autorizador, igual que en el wizard de reembolso.

  * Si el cliente decide bloquear futuras solicitudes, el estado del
    contrato transiciona a ``anulado_devolucion`` (cancelled) o
    ``desistido_devolucion`` (withdrawn). La FSM del modelo
    ``_ALLOWED_STATE_TRANSITIONS`` ya incluye estas transiciones desde
    el trabajo paralelo del grupo Documentacion.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleCreditNoReembolsoWizard(models.TransientModel):
    _name = 'sale.credit.no.reembolso.wizard'
    _description = 'No Solicitar Reembolso (Solicitud Escrita)'

    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id',
        readonly=True,
    )

    # ---------- Datos del contrato ----------------------------------------
    current_state = fields.Char(
        string='Estado Actual',
        related='credit_id.process_state_label',
        readonly=True,
    )
    current_state_tech = fields.Selection(
        string='Estado Tecnico',
        related='credit_id.state',
        readonly=True,
    )
    capital_pagado = fields.Monetary(
        string='Capital Pagado',
        currency_field='currency_id',
        compute='_compute_capital_pagado',
        readonly=True,
    )

    # ---------- Solicitud escrita -----------------------------------------
    fecha_solicitud_escrita = fields.Date(
        string='Fecha de la Solicitud Escrita',
        required=True,
        default=fields.Date.context_today,
    )
    motivo = fields.Text(
        string='Motivo / Resumen de Solicitud',
        required=True,
        help='Resumen de la solicitud escrita del cliente por la que decide '
             'no solicitar reembolso ni nota de credito. Obligatorio para '
             'auditoria (minimo 20 caracteres).',
    )
    documentacion_autoriza = fields.Many2one(
        'res.users',
        string='Autorizado por (Documentacion)',
        required=True,
        domain=lambda self: self._domain_documentacion_autoriza(),
        help='Usuario de Documentacion que revisa y firma la solicitud '
             'escrita del cliente. Filtrado por el grupo de Documentacion '
             '(user / manager) o Gerencia de Credito.',
    )

    @api.model
    def _domain_documentacion_autoriza(self):
        group_ids = [
            self.env.ref(xmlid).id
            for xmlid in (
                'cjg_finance.group_documentation_user',
                'cjg_finance.group_documentation_manager',
                'cjg_finance.group_credit_manager',
            )
        ]
        return [('groups_id', 'in', group_ids)]
    bloquea_futuro_reembolso = fields.Boolean(
        string='Bloquear futuras solicitudes de reembolso',
        default=True,
        help='Si esta activo, el contrato transiciona a un estado terminal '
             'que bloquea cualquier solicitud de reembolso posterior '
             '(el capital pagado queda definitivamente como ingreso de la '
             'empresa). Si NO esta activo, solo se registra la decision '
             'pero el contrato permanece en su estado actual.',
    )

    # ---------------------------------------------------------------------
    # Defaults / Computes
    # ---------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        credit = self.env['sale.credit'].browse(
            self.env.context.get('active_id') or values.get('credit_id')
        )
        if credit and credit.exists():
            values.setdefault('credit_id', credit.id)
        return values

    @api.depends('credit_id.amount_total', 'credit_id.credit_Adeudado')
    def _compute_capital_pagado(self):
        for wiz in self:
            if not wiz.credit_id:
                wiz.capital_pagado = 0.0
                continue
            capital_total = wiz.credit_id.amount_total or 0.0
            capital_pendiente = wiz.credit_id.credit_Adeudado or 0.0
            wiz.capital_pagado = max(0.0, capital_total - capital_pendiente)

    # ---------------------------------------------------------------------
    # Action
    # ---------------------------------------------------------------------
    def action_confirm_no_reembolso(self):
        """Registrar la decision del cliente de NO solicitar reembolso.

        - Valida que el contrato este en estado terminal elegible
          (cancelled / withdrawn) y que la decision no este ya registrada.
        - Valida que el motivo tenga minimo 20 caracteres (auditoria).
        - Setea los campos ``no_refund_*`` del contrato (reutiliza los
          campos existentes del modelo).
        - Si ``bloquea_futuro_reembolso`` esta activo, transiciona el
          contrato a estado terminal de devolucion (FSM valida).
        - Deja trazabilidad completa en el chatter.
        """
        self.ensure_one()
        credit = self.credit_id

        if credit.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                "Solo se puede registrar 'No solicitar reembolso' para "
                "contratos en estado Anulado o Desistido. "
                "Contrato %s en estado: %s."
            ) % (credit.name, credit.process_state_label or credit.state))

        if credit.no_refund_registered:
            raise UserError(_(
                "El contrato %s ya tiene registrada la decision de NO "
                "reembolso. No se puede duplicar el registro."
            ) % credit.name)

        motivo_clean = (self.motivo or '').strip()
        if len(motivo_clean) < 20:
            raise ValidationError(_(
                "El motivo debe tener al menos 20 caracteres para "
                "auditoria (caracteres actuales: %s)."
            ) % len(motivo_clean))

        with self.env.cr.savepoint():
            # 1. Marcar el contrato con la decision de NO reembolso.
            #    Reutilizamos los campos existentes (no_refund_*) para
            #    mantener una sola fuente de verdad con el badge del form
            #    y con action_register_no_refund.
            credit.write({
                'no_refund_registered': True,
                'no_refund_date': self.fecha_solicitud_escrita,
                'no_refund_user_id': self.documentacion_autoriza.id,
            })

            # 2. Si bloquea_futuro_reembolso, transicionar a estado
            #    terminal. La FSM (_ALLOWED_STATE_TRANSITIONS) valida la
            #    transicion.
            transitioned = False
            if self.bloquea_futuro_reembolso:
                if credit.state == 'cancelled':
                    credit.write({'state': 'anulado_devolucion'})
                    transitioned = True
                elif credit.state == 'withdrawn':
                    credit.write({'state': 'desistido_devolucion'})
                    transitioned = True

            # 3. Trazabilidad en chatter.
            bloquea_label = 'Si' if self.bloquea_futuro_reembolso else 'No'
            estado_final = dict(credit._fields['state'].selection).get(
                credit.state, credit.state
            )
            credit.message_post(
                body=_(
                    '<strong>Opcion 2: NO Solicitar Reembolso registrada</strong><br/>'
                    'El cliente decidio por escrito NO solicitar reembolso '
                    'ni nota de credito. El capital pagado queda en los '
                    'ingresos de la empresa.<br/>'
                    '<ul>'
                    '<li>Contrato: %s</li>'
                    '<li>Estado inicial: %s</li>'
                    '<li>Capital pagado (reconocido como ingreso): %s</li>'
                    '<li>Fecha de la solicitud escrita: %s</li>'
                    '<li>Autorizado por Documentacion: %s</li>'
                    '<li>Bloquea futuras solicitudes de reembolso: <strong>%s</strong></li>'
                    '<li>Estado final del contrato: <strong>%s</strong></li>'
                    '<li>Motivo / Resumen: %s</li>'
                    '</ul>'
                ) % (
                    credit.name,
                    self.current_state or credit.state,
                    self.capital_pagado,
                    self.fecha_solicitud_escrita,
                    self.documentacion_autoriza.name,
                    bloquea_label,
                    estado_final,
                    motivo_clean,
                ),
                subject=_('No Solicitar Reembolso (solicitud escrita)'),
            )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Contrato'),
            'res_model': 'sale.credit',
            'res_id': credit.id,
            'view_mode': 'form',
            'target': 'current',
        }
