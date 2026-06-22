# -*- coding: utf-8 -*-
"""
TRACK 3 (F10) — Status auto-change on aging.

Replica el flujo del legacy:
    testarossa/php_script/script_cambio_estatus_contratos.php

El legacy ejecuta un script que cambia el estatus de los contratos según
el aging (días sin pago):
    - 31 a 45 días sin pago → estatus 28 (POR ANULAR / POSIBLE A ANULAR)
    - 61+ días sin pago     → estatus 23 (POR DESISTIR / POSIBLE A DESISTIR)

Diseño Odoo:
    - Modelo `cjg_finance.status.aging.audit` (log histórico) — una fila
      por cambio de status automático.
    - Método `_cron_change_status_aging` en el modelo `sale.credit`.
    - ir.cron `ir_cron_status_change_aging` ejecuta diario.
    - Reglas:
        * Cuota vencida > 30 días → 'withdrawing' (por desistir)
        * Cuota vencida > 60 días → 'withdrawn' (desistido)
        * Cuota vencida > 90 días → 'legal' (en legal)
    - Cada cambio se audita en chatter (mail.message) y en
      `cjg_finance.status.aging.audit`.
"""
from odoo import api, fields, models, _


class CjgFinanceStatusAgingAudit(models.Model):
    """
    Auditoría de cambios de status por aging (1 fila por cambio automático).
    Permite responder: ¿cuándo este contrato pasó a withdrawing? ¿quién
    lo hizo? ¿por qué regla de aging?
    """
    _name = 'cjg.finance.status.aging.audit'
    _description = 'Auditoría de Cambio de Status por Aging'
    _order = 'create_date desc, id desc'
    _log_access = True

    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        ondelete='cascade',
        index=True,
    )
    credit_name = fields.Char(
        string='Contrato (texto)',
        related='credit_id.name',
        store=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        related='credit_id.partner_id',
        store=True,
    )
    from_state = fields.Selection(
        selection='_get_credit_states',
        string='Estado Origen',
    )
    to_state = fields.Selection(
        selection='_get_credit_states',
        string='Estado Destino',
        required=True,
    )
    rule = fields.Selection([
        ('overdue_30', 'Cuota vencida > 30 días'),
        ('overdue_60', 'Cuota vencida > 60 días'),
        ('overdue_90', 'Cuota vencida > 90 días'),
        ('revert_paid', 'Reversión: cuotas pagadas'),
        ('manual', 'Manual'),
    ], string='Regla Aplicada', required=True)
    days_overdue = fields.Integer(
        string='Días de Atraso',
        help='Días de atraso del contrato en el momento del cambio.',
    )
    affected_lines = fields.Integer(
        string='# Cuotas Vencidas',
        help='Cantidad de cuotas vencidas que dispararon el cambio.',
    )
    note = fields.Text(string='Nota')
    executed_by = fields.Many2one(
        'res.users',
        string='Ejecutado Por',
        default=lambda self: self.env.user,
    )

    @api.model
    def _get_credit_states(self):
        """Devuelve el selection de states del modelo sale.credit."""
        return self.env['sale.credit']._fields['state'].selection

    def name_get(self):
        result = []
        for rec in self:
            label = '%s: %s → %s (%s)' % (
                rec.credit_name or '?',
                rec.from_state or '—',
                rec.to_state,
                rec.rule,
            )
            result.append((rec.id, label))
        return result
