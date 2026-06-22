# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from calendar import monthrange


class CierreContable(models.Model):
    _name = 'cierre.contable'
    _description = 'Cierre Contable Mensual (Legacy: tabla cierres)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'ano desc, mes desc, id desc'
    _rec_name = 'display_name'

    name = fields.Char(
        string='Nombre',
        compute='_compute_name',
        store=True,
        readonly=True,
    )
    display_name = fields.Char(
        string='Periodo',
        compute='_compute_display_name',
        store=True,
        readonly=True,
    )
    ano = fields.Integer(
        string='Año',
        required=True,
        tracking=True,
        index=True,
    )
    mes = fields.Integer(
        string='Mes',
        required=True,
        tracking=True,
        index=True,
        help='Mes contable (1-12).',
    )
    fecha_inicio_ventas = fields.Date(
        string='Fecha Inicio Ventas',
        required=True,
        tracking=True,
    )
    fecha_fin_ventas = fields.Date(
        string='Fecha Fin Ventas',
        required=True,
        tracking=True,
    )
    state = fields.Selection([
        ('open', 'Abierto'),
        ('closed', 'Cerrado'),
    ], string='Estado', default='open', required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    notes = fields.Text(string='Notas')

    _sql_constraints = [
        (
            'company_ano_mes_unique',
            'UNIQUE(company_id, ano, mes)',
            'Ya existe un cierre contable para esa compañía, año y mes.',
        ),
    ]

    _mes_selection = [
        (1, 'Enero'),
        (2, 'Febrero'),
        (3, 'Marzo'),
        (4, 'Abril'),
        (5, 'Mayo'),
        (6, 'Junio'),
        (7, 'Julio'),
        (8, 'Agosto'),
        (9, 'Septiembre'),
        (10, 'Octubre'),
        (11, 'Noviembre'),
        (12, 'Diciembre'),
    ]

    @api.model
    def _get_mes_selection(self):
        return self._mes_selection

    @api.depends('mes', 'ano')
    def _compute_name(self):
        for record in self:
            if record.mes and record.ano:
                record.name = 'S{mes}/{ano}'.format(
                    mes=int(record.mes),
                    ano=int(record.ano),
                )
            else:
                record.name = _('Nuevo')

    @api.depends('mes', 'ano')
    def _compute_display_name(self):
        for record in self:
            if record.mes and record.ano:
                record.display_name = '{mes:02d}-{ano}'.format(
                    mes=int(record.mes),
                    ano=int(record.ano),
                )
            else:
                record.display_name = _('Nuevo')

    @api.constrains('mes')
    def _check_mes_range(self):
        for record in self:
            if not (1 <= record.mes <= 12):
                raise ValidationError(_('El mes debe estar entre 1 y 12.'))

    @api.constrains('ano')
    def _check_ano_range(self):
        for record in self:
            if record.ano < 1900 or record.ano > 2999:
                raise ValidationError(_('El año debe estar entre 1900 y 2999.'))

    @api.constrains('fecha_inicio_ventas', 'fecha_fin_ventas')
    def _check_fechas_coherentes(self):
        for record in self:
            if record.fecha_inicio_ventas and record.fecha_fin_ventas:
                if record.fecha_fin_ventas < record.fecha_inicio_ventas:
                    raise ValidationError(_(
                        'La fecha fin de ventas (%s) debe ser mayor o igual '
                        'que la fecha inicio de ventas (%s).'
                    ) % (
                        record.fecha_fin_ventas,
                        record.fecha_inicio_ventas,
                    ))

    @api.model
    def _calcular_rango_mes(self, ano, mes):
        """Devuelve (fecha_inicio, fecha_fin) para un (ano, mes) dado.

        Refleja la convención legacy de Testarossa donde la fecha de fin
        es el último día natural del mes.
        """
        if not ano or not mes or not (1 <= int(mes) <= 12):
            return False, False
        last_day = monthrange(int(ano), int(mes))[1]
        inicio = fields.Date.to_date('{ano}-{mes:02d}-01'.format(
            ano=int(ano), mes=int(mes)))
        fin = fields.Date.to_date('{ano}-{mes:02d}-{day:02d}'.format(
            ano=int(ano), mes=int(mes), day=last_day))
        return inicio, fin

    def action_cerrar(self):
        for record in self:
            if record.state == 'closed':
                continue
            record.write({'state': 'closed'})

    def action_reabrir(self):
        for record in self:
            if record.state == 'open':
                continue
            record.write({'state': 'open'})

    def action_recalcular_rango(self):
        """Renueva fecha_inicio/fin a partir del mes y año del registro."""
        for record in self:
            inicio, fin = self._calcular_rango_mes(record.ano, record.mes)
            if inicio and fin:
                record.write({
                    'fecha_inicio_ventas': inicio,
                    'fecha_fin_ventas': fin,
                })
