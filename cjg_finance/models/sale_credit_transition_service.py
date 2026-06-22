# -*- coding: utf-8 -*-
"""
Servicio central de transiciones FSM para sale.credit
=======================================================

Este servicio resuelve el META-PATTERN detectado en la auditoría D12 (cierre de
contratos) donde múltiples módulos satélite (D6, D7, D8, D11) mutaban
directamente ``sale.credit.state`` sin coordinar con la máquina de estados
central definida en ``cjg_finance/models/sale/sale_credit.py``::

    _ALLOWED_STATE_TRANSITIONS = {
        'draft':     {'requested', 'cancelled', 'refuse'},
        'requested': {'pending', 'approved', 'refuse', 'cancelled'},
        ...
        'closed':    set(),  # terminal
    }

Problema (GAP-12.03): habilitar la validación de ``write()`` rompía los writes
directos en módulos satélite (e.g. ``collection_acta_cierre.py:204`` y :324).

Solución: este servicio expone una API única que:
    1. Valida la transición contra el FSM.
    2. Si la transición directa no es válida, intenta encontrar una ruta
       indirecta (BFS) y la ejecuta paso a paso en un savepoint.
    3. Si no hay ruta, retorna error NO rompe el flujo llamador.
    4. Permite bypass con ``force=True`` (casos justificados).
    5. Centraliza efectos colaterales (setear ``closed_date``, ``message_post``).

Uso típico (desde un wizard, cron o módulo satélite)::

    service = self.env['sale.credit.transition.service']
    result = service.transition_with_path(
        credit,
        target_state='withdrawn',
        reason='Acta de desistimiento 2026-001',
    )
    if not result['success']:
        _logger.warning('No se pudo transicionar: %s', result.get('reason'))
        # continuar con el siguiente crédito
    else:
        # transición (directa o indirecta) exitosa
        pass

History:
    - 2026-06-15: creado en Sprint 23 para resolver GAP-12.03 + meta-pattern.
"""

import logging
from collections import deque

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.fields import Date

_logger = logging.getLogger(__name__)


class SaleCreditTransitionService(models.AbstractModel):
    """Servicio central de transiciones FSM de ``sale.credit``.

    Modelo abstracto (no persistido) — usable vía ``self.env[...]`` desde
    cualquier módulo del ecosistema core_credito.
    """

    _name = 'sale.credit.transition.service'
    _description = 'Servicio central de transiciones FSM de sale.credit'

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @api.model
    def transition(self, credit, target_state, reason='', force=False):
        """Transición directa (un solo paso) a ``target_state``.

        :param credit: ``sale.credit`` recordset (típicamente 1 registro).
        :param target_state: estado destino (debe existir en la FSM).
        :param reason: texto libre para ``message_post`` (trazabilidad).
        :param force: si True, bypasea validación (loggea warning).
        :return: ``dict`` con ``success``, ``old_state``, ``new_state``,
                 ``reason`` (en caso de fallo) y ``forced`` (bool).
        """
        credit.ensure_one()
        old_state = credit.state

        # Si ya está en el estado destino, no-op exitoso
        if old_state == target_state:
            return {
                'success': True,
                'old_state': old_state,
                'new_state': target_state,
                'reason': 'already in target state',
                'forced': False,
            }

        allowed = self._get_fsm().get(old_state, set())
        is_valid = target_state in allowed

        if not is_valid and not force:
            return {
                'success': False,
                'old_state': old_state,
                'new_state': None,
                'reason': _(
                    'Transición inválida: %(old)s → %(new)s. '
                    'Estados permitidos desde %(old)s: %(allowed)s.'
                ) % {
                    'old': old_state,
                    'new': target_state,
                    'allowed': sorted(allowed) if allowed else '(terminal)',
                },
                'forced': False,
            }

        if not is_valid and force:
            _logger.warning(
                'Bypaseando FSM en sale.credit %s: %s → %s (force=True). Reason: %s',
                credit.display_name, old_state, target_state, reason,
            )

        self._apply_transition(credit, target_state, reason)
        return {
            'success': True,
            'old_state': old_state,
            'new_state': target_state,
            'reason': reason,
            'forced': force and not is_valid,
        }

    @api.model
    def transition_with_path(self, credit, target_state, reason=''):
        """Transición que puede requerir múltiples pasos (BFS por la FSM).

        Útil cuando el estado actual no puede ir directo al destino, pero
        existe una cadena válida (e.g. ``approved → active → withdrawing →
        withdrawn``).

        :return: ``dict`` con ``success``, ``path`` (lista de estados),
                 ``reason`` (en caso de fallo).
        """
        credit.ensure_one()
        old_state = credit.state

        if old_state == target_state:
            return {
                'success': True,
                'old_state': old_state,
                'new_state': target_state,
                'path': [old_state],
                'reason': 'already in target state',
            }

        allowed = self._get_fsm().get(old_state, set())
        # Caso feliz: transición directa
        if target_state in allowed:
            self._apply_transition(credit, target_state, reason)
            return {
                'success': True,
                'old_state': old_state,
                'new_state': target_state,
                'path': [old_state, target_state],
                'reason': reason,
            }

        # Buscar ruta indirecta
        path = self._find_transition_path(old_state, target_state)
        if not path:
            return {
                'success': False,
                'old_state': old_state,
                'new_state': None,
                'path': [],
                'reason': _(
                    'No hay ruta de FSM de %(old)s a %(new)s. '
                    'Estados permitidos desde %(old)s: %(allowed)s.'
                ) % {
                    'old': old_state,
                    'new': target_state,
                    'allowed': sorted(allowed) if allowed else '(terminal)',
                },
            }

        # Ejecutar la ruta completa en un savepoint (rollback si algo falla)
        try:
            with self.env.cr.savepoint():
                for step_state in path[1:]:  # omitir estado inicial
                    self._apply_transition(credit, step_state, reason)
        except Exception as e:
            _logger.error(
                'Falla ejecutando ruta FSM %s para crédito %s: %s',
                path, credit.display_name, e,
            )
            return {
                'success': False,
                'old_state': old_state,
                'new_state': None,
                'path': path,
                'reason': str(e),
            }

        return {
            'success': True,
            'old_state': old_state,
            'new_state': target_state,
            'path': path,
            'reason': reason,
        }

    @api.model
    def get_allowed_targets(self, credit):
        """Retorna la lista de estados alcanzables directamente desde el estado actual.

        :return: ``list`` de strings (puede estar vacía si el estado es terminal).
        """
        credit.ensure_one()
        return sorted(self._get_fsm().get(credit.state, set()))

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @api.model
    def _find_transition_path(self, source_state, target_state):
        """BFS por el grafo FSM para encontrar la ruta más corta.

        :return: ``list`` de estados desde ``source_state`` hasta
                 ``target_state`` inclusive. ``[]`` si no hay ruta.
        """
        fsm = self._get_fsm()
        if source_state not in fsm or target_state not in fsm:
            return []

        if source_state == target_state:
            return [source_state]

        # BFS
        queue = deque([(source_state, [source_state])])
        visited = {source_state}
        while queue:
            current, path = queue.popleft()
            for neighbor in fsm.get(current, set()):
                if neighbor in visited:
                    continue
                new_path = path + [neighbor]
                if neighbor == target_state:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))
        return []

    @api.model
    def _get_fsm(self):
        """Lee ``_ALLOWED_STATE_TRANSITIONS`` del modelo ``sale.credit``.

        Se obtiene dinámicamente (no copiamos la estructura) para que un
        cambio en el modelo central se refleje automáticamente aquí.
        """
        SaleCredit = self.env['sale.credit']
        return getattr(SaleCredit, '_ALLOWED_STATE_TRANSITIONS', {})

    @api.model
    def _apply_transition(self, credit, target_state, reason):
        """Ejecuta el write + efectos colaterales centralizados.

        Efectos:
            - ``state = target_state``
            - Si ``target_state == 'closed'`` → ``closed_date = today``
            - ``message_post`` con la razón del cambio
        """
        vals = {'state': target_state}
        if target_state == 'closed':
            vals['closed_date'] = Date.today()
        elif target_state in ('forgiven', 'cancelled', 'withdrawn'):
            # Mantener closed_date si ya estaba seteado
            if not credit.closed_date:
                # No setear — solo aplica a 'closed'
                pass

        credit.write(vals)
        credit.message_post(
            body=_(
                'Transición FSM: %(old)s → %(new)s. Motivo: %(reason)s'
            ) % {
                'old': credit.state if False else '(ver log)',  # ya actualizado
                'new': target_state,
                'reason': reason or '(sin motivo especificado)',
            },
        )
