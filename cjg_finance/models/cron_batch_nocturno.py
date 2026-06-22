# -*- coding: utf-8 -*-
"""
Batch nocturno que replica el comportamiento del script legacy de Testarossa
``cobros_actualizar_pagos_contratos_mes.php``.

Operaciones:
  1. Actualizar ``sale.credit.total_payments_count`` y ``sale.credit.last_payment_date``
     (equivalentes legacy a ``cobros_contratos.total_pagos_realizado`` y
     ``cobros_contratos.fecha_ultimo_pago``).
  2. Marcar contratos ``state='withdrawing'`` (legacy estado 28 "POR ANULAR")
     si el cliente no pagó la cuota del mes actual y la fecha esperada
     supera los 30 días de gracia.
  3. Escribir un snapshot de auditoría en el log estructurado
     (``[BATCH NOCTURNO]``) — el log de Odoo actúa como
     ``cjg.finance.batch.nightly.log``.

Notas arquitectónicas:
  * El cron está DESACTIVADO por defecto (``active=False``). Activar SOLO
    después de validar en staging (ver ``cjg_finance/data/cron.xml``).
  * Esta lógica convive con ``_cron_auto_withdraw_contracts`` (3+ cuotas
    vencidas). El batch nocturno usa el criterio de 30 días de gracia
    sobre la cuota más reciente — son DOS políticas distintas para el
    mismo estado, no duplicación.
  * Campos ``total_payments_count`` y ``last_payment_date`` no existían
    en ``sale.credit``; se añaden aquí por ``_inherit`` para no tocar
    ``sale_credit.py`` (mínimo impacto).
"""
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class CjgFinanceBatchNocturno(models.AbstractModel):
    _name = 'cjg.finance.batch.nocturno'
    _description = 'Batch nocturno de actualización de pagos (legacy testarossa)'

    @api.model
    def cron_update_pagos_contratos_mes(self):
        """Replica ``cobros_actualizar_pagos_contratos_mes.php``.

        Se ejecuta diariamente. Para cada contrato activo:
          - Actualiza ``total_payments_count`` y ``last_payment_date``
            agregando pagos con ``state in ('validated', 'paid')``.
          - Si el cliente no pagó la cuota del mes actual y ya pasaron
            más de 30 días desde la fecha esperada, marca el contrato
            como ``state='withdrawing'`` (POR ANULAR en legacy, estado 28).

        :returns: dict con resumen de la corrida (para tests y monitor).
        """
        _logger.info("[BATCH NOCTURNO] Iniciando actualizacion de pagos del mes...")

        result = {
            'contracts_processed': 0,
            'contracts_marked_anular': 0,
            'contracts_marked_desistir': 0,
            'errors': [],
        }

        # Contratos activos: solo estados de vida real del modelo
        # (sale_credit.py:434-450). NO incluye 'pending'/'verified'/'requested'
        # porque esos no son estados finales de contrato.
        active_states = ('approved', 'active')
        contracts = self.env['sale.credit'].search([
            ('state', 'in', active_states),
        ])

        today = fields.Date.context_today(self)

        for contract in contracts:
            try:
                with self.env.cr.savepoint():
                    self._update_contract_payment_totals(contract)
                    result['contracts_processed'] += 1
                    # F10 — legado estatus 28: 30+ días sin pago del mes
                    if self._should_mark_as_anular(contract, today):
                        contract.write({'state': 'withdrawing'})
                        contract.message_post(
                            body=_(
                                "Contrato marcado como POR ANULAR (withdrawing) por "
                                "el batch nocturno: cuota del mes actual sin pago y "
                                "fecha esperada superada en +30 dias."
                            )
                        )
                        result['contracts_marked_anular'] += 1
                    # F10 — legado estatus 23: 61+ días sin pago (excl. 1ra cuota)
                    elif self._should_mark_as_desistir(contract, today):
                        contract.write({'state': 'withdrawing'})
                        contract.message_post(
                            body=_(
                                "Contrato marcado como POR DESISTIR (withdrawing, "
                                "legacy estatus 23) por el batch nocturno: ultimo "
                                "pago hace mas de 61 dias y no es primera cuota."
                            )
                        )
                        result['contracts_marked_desistir'] += 1
            except Exception as e:
                _logger.exception(
                    "[BATCH NOCTURNO] Error procesando contrato %s: %s",
                    contract.name, str(e),
                )
                result['errors'].append({
                    'contract': contract.name,
                    'error': str(e),
                })

        _logger.info(
            "[BATCH NOCTURNO] Finalizado. Procesados: %s, "
            "Marcados POR ANULAR (28): %s, Marcados POR DESISTIR (23): %s, "
            "Errores: %s",
            result['contracts_processed'],
            result['contracts_marked_anular'],
            result['contracts_marked_desistir'],
            len(result['errors']),
        )
        return result

    def _update_contract_payment_totals(self, contract):
        """Actualiza ``total_payments_count`` y ``last_payment_date``.

        Agrega pagos ``sale.credit.payment`` con estado ``validated`` o ``paid``
        (los únicos terminales en ``sale_credit_payment.py:17-22``).
        """
        payments = self.env['sale.credit.payment'].search([
            ('credit_id', '=', contract.id),
            ('state', 'in', ('validated', 'paid')),
        ])
        if not payments:
            contract.write({
                'total_payments_count': 0,
                'last_payment_date': False,
            })
            return

        # ``payment_date`` es compute+inverse+store (sale_credit_payment.py:77)
        # y delega en ``date`` del recibo POS padre. Usar ``payment_date`` es
        # la API pública y estable.
        dates = [p.payment_date for p in payments if p.payment_date]
        contract.write({
            'total_payments_count': len(payments),
            'last_payment_date': max(dates) if dates else False,
        })

    def _should_mark_as_anular(self, contract, today):
        """Determina si el contrato debe marcarse POR ANULAR.

        Regla legacy (testarossa estado 28): si la cuota más reciente
        esperada está vencida por más de 30 días y no se ha pagado nada,
        marcar el contrato como ``withdrawing``.

        Criterio explícito (no duplica ``_cron_auto_withdraw_contracts``):
          - Cuota más reciente por ``expected_date_payment`` no está pagada.
          - Han pasado más de 30 días desde ``expected_date_payment``.
          - ``amount_paid_total`` de esa línea es 0.
        """
        if not contract.credit_lines:
            return False

        pending_lines = contract.credit_lines.filtered(
            lambda l: l.state in ('pending', 'paid_overdue')
        )
        if not pending_lines:
            return False

        latest_line = max(
            pending_lines,
            key=lambda l: l.expected_date_payment or fields.Date.from_string('1900-01-01'),
        )
        expected = latest_line.expected_date_payment
        if not expected:
            return False

        # ``fields.Date.from_string`` defensivo por si llegara como str
        if isinstance(expected, str):
            expected = fields.Date.from_string(expected)

        days_overdue = (today - expected).days
        return days_overdue > 30 and latest_line.amount_paid_total == 0.0

    def _should_mark_as_desistir(self, contract, today):
        """Determina si el contrato debe marcarse POR DESISTIR.

        Regla legacy (testarossa estado 23, ``script_cambio_estatus_contratos.php``):
        si el último pago del contrato fue hace más de 61 días y la línea
        más reciente NO es la primera cuota, marcar el contrato como
        ``withdrawing`` (legacy estado 23 = POR DESISTIR).

        Criterio explícito:
          - ``last_payment_date`` (legacy ``cobros_contratos.fecha_ultimo_pago``)
            debe existir y tener más de 61 días de antigüedad.
          - La línea de crédito más reciente NO es la primera cuota
            (``sequence > 1`` o ``is_first_installment is False``).
        """
        if not contract.last_payment_date:
            return False
        if not contract.credit_lines:
            return False

        # Excluir contratos donde la única línea es la primera cuota
        # (legacy: ``cobros_contratos.categoria != 'PRIMERA_CUOTA'``)
        non_first_lines = contract.credit_lines.filtered(
            lambda l: not getattr(l, 'is_first_installment', False)
                      and (getattr(l, 'sequence', 1) or 1) > 1
        )
        if not non_first_lines:
            return False

        last_payment = contract.last_payment_date
        if isinstance(last_payment, str):
            last_payment = fields.Date.from_string(last_payment)

        days_since_last = (today - last_payment).days
        return days_since_last > 61


class SaleCreditBatchNocturnoFields(models.Model):
    """Añade los campos legacy ``total_pagos_realizado`` / ``fecha_ultimo_pago``
    al modelo ``sale.credit`` mediante ``_inherit``, sin modificar
    ``sale_credit.py`` (mínimo impacto).
    """
    _inherit = 'sale.credit'

    total_payments_count = fields.Integer(
        string="Total Pagos Realizados (Legacy)",
        default=0,
        readonly=True,
        help="Cantidad de pagos validados/pagados. "
             "Actualizado por el batch nocturno (legacy testarossa: "
             "cobros_contratos.total_pagos_realizado).",
    )
    last_payment_date = fields.Date(
        string="Fecha Ultimo Pago (Legacy)",
        readonly=True,
        help="Fecha del pago más reciente validado/pagado. "
             "Actualizado por el batch nocturno (legacy testarossa: "
             "cobros_contratos.fecha_ultimo_pago).",
    )
