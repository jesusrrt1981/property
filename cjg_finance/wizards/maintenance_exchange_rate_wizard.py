# -*- coding: utf-8 -*-

from odoo import fields, models, _
from odoo.exceptions import UserError


class MaintenanceExchangeRateWizard(models.TransientModel):
    _name = 'maintenance.exchange.rate.wizard'
    _description = 'Actualizar tasa de mantenimientos'

    use_manual_exchange_rate = fields.Boolean(
        string='Modificar Tasa?',
        default=True,
        help='Si está activo, los mantenimientos seleccionados usarán la tasa indicada en POS.'
    )
    manual_exchange_rate = fields.Float(
        string='Tasa de Mantenimiento',
        digits=(16, 6),
        help='Tasa fija negociada para convertir el mantenimiento en el POS.'
    )

    def action_apply(self):
        active_ids = self.env.context.get('active_ids') or []
        contracts = self.env['maintenance.contract'].browse(active_ids).exists()
        if not contracts:
            raise UserError(_('Seleccione al menos un contrato de mantenimiento.'))

        if self.use_manual_exchange_rate and self.manual_exchange_rate <= 0.0:
            raise UserError(_('Debe indicar una tasa mayor que cero.'))

        contracts.write({
            'use_manual_exchange_rate': self.use_manual_exchange_rate,
            'manual_exchange_rate': self.manual_exchange_rate if self.use_manual_exchange_rate else 0.0,
        })
        return {'type': 'ir.actions.act_window_close'}
