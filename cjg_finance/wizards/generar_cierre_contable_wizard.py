# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError


class GenerarCierreContableWizard(models.TransientModel):
    _name = 'generar.cierre.contable.wizard'
    _description = 'Generar los 12 cierres contables de un año'

    ano = fields.Integer(
        string='Año',
        required=True,
        default=lambda self: fields.Date.today().year,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
    )
    sobreescribir_existentes = fields.Boolean(
        string='Sobreescribir existentes',
        default=False,
        help='Si está activo, los cierres ya creados para ese año se '
             'sobrescriben con las fechas calculadas.',
    )

    def action_generar(self):
        self.ensure_one()
        if not (1900 <= self.ano <= 2999):
            raise UserError(_('El año debe estar entre 1900 y 2999.'))

        Cierre = self.env['cierre.contable']
        creados = 0
        actualizados = 0
        omitidos = 0
        for mes in range(1, 13):
            inicio, fin = Cierre._calcular_rango_mes(self.ano, mes)
            existente = Cierre.search([
                ('company_id', '=', self.company_id.id),
                ('ano', '=', self.ano),
                ('mes', '=', mes),
            ], limit=1)
            if existente:
                if self.sobreescribir_existentes:
                    existente.write({
                        'fecha_inicio_ventas': inicio,
                        'fecha_fin_ventas': fin,
                    })
                    actualizados += 1
                else:
                    omitidos += 1
                continue
            Cierre.create({
                'ano': self.ano,
                'mes': mes,
                'fecha_inicio_ventas': inicio,
                'fecha_fin_ventas': fin,
                'company_id': self.company_id.id,
            })
            creados += 1

        mensaje = _('Año %s: %d creados, %d actualizados, %d omitidos.') % (
            self.ano, creados, actualizados, omitidos,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cierres generados'),
                'message': mensaje,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _('Cierres Contables'),
                    'res_model': 'cierre.contable',
                    'view_mode': 'tree,form',
                    'domain': [
                        ('company_id', '=', self.company_id.id),
                        ('ano', '=', self.ano),
                    ],
                },
            },
        }
