# -*- coding: utf-8 -*-
"""
Wizard de Reembolso 70/30 — contratos anulados/desistidos con 12+ meses.

Replica el procedimiento del documento "Proceso reactivacion y Mejora":
  - Después de 12+ meses de la anulación, el cliente puede solicitar reembolso
    por escrito.
  - Se reconoce el 70% del capital pagado al cliente.
  - El 30% del capital + TODOS los intereses pagados quedan como ingreso
    de la empresa.
  - Se genera una NC contable (cargo tipo "credit" con monto positivo) y
    se notifica a Contabilidad para emisión de cheque/transferencia.

Adaptaciones aplicadas al esquema real del módulo:
  * ``paid_capital`` NO es un campo almacenado en ``sale.credit``;
    se computa en el propio wizard a partir de ``amount_total`` y
    ``credit_Adeudado`` (mismo patrón que ``sale_credit_reactivation_wizard``).
  * ``sale.credit.charge.charge_type`` solo admite ``'charge'`` / ``'credit'``
    y su constraint exige ``amount > 0``. Se usa ``'credit'`` con monto
    positivo, no negativo.
  * El grupo de Documentación (``cjg_finance.group_documentation_user``
    y ``cjg_finance.group_documentation_manager``) ya está creado vía
    ``security/credito_documentation_security.xml``. El dominio del campo
    ``documentacion_autoriza`` los incluye, junto con ``group_credit_manager``
    como red de seguridad.
  * El estado del contrato SÍ se transiciona: ``cancelled`` →
    ``anulado_devolucion`` y ``withdrawn`` → ``desistido_devolucion``
    (estos estados ya fueron añadidos a ``_ALLOWED_STATE_TRANSITIONS``
    y al Selection de ``state`` por la tarea paralela del Grupo
    Documentación). La transición es validada por el ``write()`` FSM.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleCreditReembolsoWizard(models.TransientModel):
    _name = 'sale.credit.reembolso.wizard'
    _description = 'Reembolso 70/30 después de 1 año (legacy)'

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
    fecha_anulacion = fields.Date(
        string='Fecha de Última Cuota',
        related='credit_id.last_payment_date',
        readonly=True,
        help='Fecha del último pago registrado en el contrato. Cuando el '
             'contrato se anula/desiste sin pagos, este campo queda vacío.',
    )
    meses_transcurridos = fields.Integer(
        string='Meses Transcurridos',
        compute='_compute_meses_transcurridos',
    )
    elegible = fields.Boolean(
        string='Elegible para Reembolso',
        compute='_compute_elegible',
    )

    # ---------- Cálculo del reembolso -------------------------------------
    capital_pagado = fields.Monetary(
        string='Capital Pagado',
        currency_field='currency_id',
        compute='_compute_paid_capital',
        readonly=True,
    )
    intereses_pagados = fields.Monetary(
        string='Intereses Pagados (Retenidos)',
        currency_field='currency_id',
        compute='_compute_intereses_pagados',
        readonly=True,
    )
    porcentaje_reembolso = fields.Float(
        string='% de Reembolso',
        default=70.0,
        required=True,
        help='Porcentaje del capital pagado que se reembolsa al cliente. '
             'Por defecto 70% según política legacy. El 30% restante + '
             'todos los intereses quedan como ingreso de la empresa.',
    )
    monto_reembolso = fields.Monetary(
        string='Monto a Reembolsar (NC)',
        currency_field='currency_id',
        compute='_compute_monto_reembolso',
        readonly=True,
    )
    monto_retenido = fields.Monetary(
        string='Monto Retenido por la Empresa',
        currency_field='currency_id',
        compute='_compute_monto_reembolso',
        readonly=True,
    )

    # ---------- Autorización ---------------------------------------------
    motivo = fields.Text(
        string='Motivo / Solicitud Escrita',
        required=True,
        help='Resumen de la solicitud de reembolso escrita por el cliente. '
             'Obligatorio para auditoría.',
    )
    documentacion_autoriza = fields.Many2one(
        'res.users',
        string='Autorizado por (Documentación)',
        required=True,
        domain=lambda self: self._domain_documentacion_autoriza(),
        help='Usuario de Documentación que revisa y autoriza la solicitud '
             '(ej. María Santana). Filtrado por el grupo de Documentación '
             '(user / manager) o Gerencia de Crédito.',
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
    def _compute_paid_capital(self):
        for wiz in self:
            if not wiz.credit_id:
                wiz.capital_pagado = 0.0
                continue
            capital_total = wiz.credit_id.amount_total or 0.0
            capital_pendiente = wiz.credit_id.credit_Adeudado or 0.0
            wiz.capital_pagado = max(0.0, capital_total - capital_pendiente)

    @api.depends('credit_id')
    def _compute_intereses_pagados(self):
        for wiz in self:
            if not wiz.credit_id:
                wiz.intereses_pagados = 0.0
                continue
            _capital, interest_paid = wiz.credit_id._get_process_paid_breakdown()
            wiz.intereses_pagados = interest_paid or 0.0

    @api.depends('fecha_anulacion')
    def _compute_meses_transcurridos(self):
        for wiz in self:
            if not wiz.fecha_anulacion:
                wiz.meses_transcurridos = 0
                continue
            today = fields.Date.context_today(wiz)
            delta = today - wiz.fecha_anulacion
            wiz.meses_transcurridos = int(delta.days / 30)

    @api.depends('meses_transcurridos', 'credit_id.state')
    def _compute_elegible(self):
        for wiz in self:
            terminal_states = ('cancelled', 'withdrawn')
            wiz.elegible = (
                wiz.meses_transcurridos >= 12
                and wiz.credit_id.state in terminal_states
            )

    @api.depends('capital_pagado', 'porcentaje_reembolso', 'intereses_pagados')
    def _compute_monto_reembolso(self):
        for wiz in self:
            pct = wiz.porcentaje_reembolso or 0.0
            if pct < 0 or pct > 100:
                wiz.monto_reembolso = 0.0
                wiz.monto_retenido = 0.0
                continue
            capital = wiz.capital_pagado or 0.0
            wiz.monto_reembolso = capital * (pct / 100.0)
            wiz.monto_retenido = (
                capital * (1.0 - pct / 100.0)
                + (wiz.intereses_pagados or 0.0)
            )

    # ---------------------------------------------------------------------
    # Eligibility / validation
    # ---------------------------------------------------------------------
    def _validate_eligibility(self):
        """Centralised guard: 12+ months AND state in cancelled/withdrawn."""
        self.ensure_one()
        credit = self.credit_id
        if credit.state not in ('cancelled', 'withdrawn'):
            raise UserError(_(
                'El contrato %s no es elegible para reembolso. '
                'Solo contratos en estado Anulado o Desistido pueden '
                'solicitar reembolso 70/30. Estado actual: %s'
            ) % (credit.name, credit.process_state_label or credit.state))
        if credit.no_refund_registered:
            raise UserError(_(
                "Este contrato tiene registrada una decision de NO "
                "reembolso por el cliente (Opcion 2). Para procesar un "
                "reembolso ahora, primero debe revertirse esa decision "
                "(contactar a Documentacion)."
            ))
        if self.meses_transcurridos < 12:
            raise UserError(_(
                'El contrato %s aún no cumple el periodo de 12 meses desde '
                'la última cuota. Meses transcurridos: %s.'
            ) % (credit.name, self.meses_transcurridos))
        if not self.fecha_anulacion:
            raise UserError(_(
                'El contrato %s no tiene fecha de última cuota registrada. '
                'No se puede calcular el periodo de 12 meses.'
            ) % credit.name)
        if self.porcentaje_reembolso < 0 or self.porcentaje_reembolso > 100:
            raise ValidationError(_(
                'El porcentaje de reembolso debe estar entre 0%% y 100%%.'
            ))

    # ---------------------------------------------------------------------
    # Action
    # ---------------------------------------------------------------------
    def action_confirm_reembolso(self):
        """Crear NC contable (cargo tipo 'credit') y registrar trazabilidad."""
        self.ensure_one()
        self._validate_eligibility()

        credit = self.credit_id
        with self.env.cr.savepoint():
            # 1. NC contable: cargo tipo 'credit' (abono) con monto positivo.
            #    La constraint del modelo exige amount > 0; el signo negativo
            #    del ejemplo original se omite porque no es válido en el
            #    esquema actual. La semántica "NC a favor del cliente" se
            #    registra en el ``reason``.
            charge = self.env['sale.credit.charge'].create({
                'credit_id': credit.id,
                'charge_type': 'credit',
                'amount': self.monto_reembolso,
                'reason': _(
                    'NC — Reembolso %s%% del capital pagado (legacy 12+ meses). '
                    'Meses transcurridos: %s. Capital pagado: %s. '
                    'Intereses retenidos: %s. Monto retenido por la empresa: %s. '
                    'Solicitado por: %s. Autorizado por: %s.'
                ) % (
                    self.porcentaje_reembolso,
                    self.meses_transcurridos,
                    self.capital_pagado,
                    self.intereses_pagados,
                    self.monto_retenido,
                    self.motivo[:200],
                    self.documentacion_autoriza.name,
                ),
                'date': fields.Date.today(),
            })
            # Aplicar la NC para que tenga efecto contable
            if hasattr(charge, 'action_post'):
                charge.action_post()

            # 2. Transición de estado: Anulado → Anulado Devolución /
            #    Desistido → Desistido Devolución. La FSM del modelo
            #    (_ALLOWED_STATE_TRANSITIONS) valida la transición.
            if credit.state == 'cancelled':
                credit.write({'state': 'anulado_devolucion'})
            elif credit.state == 'withdrawn':
                credit.write({'state': 'desistido_devolucion'})

            # 3. Trazabilidad en el chatter del contrato.
            credit.message_post(
                body=_(
                    '<strong>Reembolso 70/30 procesado</strong><br/>'
                    'Monto a reembolsar (NC): %s<br/>'
                    'Capital pagado base: %s<br/>'
                    'Intereses retenidos por la empresa: %s<br/>'
                    'Monto total retenido: %s<br/>'
                    'Porcentaje aplicado: %s%%<br/>'
                    'Meses transcurridos desde la última cuota: %s<br/>'
                    'Cargo contable: <a href="#id=%d&model=sale.credit.charge">%s</a><br/>'
                    'Estado del contrato: <strong>%s</strong><br/>'
                    'Motivo: %s<br/>'
                    'Autorizado por: %s'
                ) % (
                    self.monto_reembolso,
                    self.capital_pagado,
                    self.intereses_pagados,
                    self.monto_retenido,
                    self.porcentaje_reembolso,
                    self.meses_transcurridos,
                    charge.id, charge.name,
                    credit.state,
                    self.motivo,
                    self.documentacion_autoriza.name,
                ),
                subject=_('Reembolso 70/30 (legacy)'),
            )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Contrato'),
            'res_model': 'sale.credit',
            'res_id': credit.id,
            'view_mode': 'form',
            'target': 'current',
        }
