# -*- coding: utf-8 -*-
# Copyright 2025 CJG
#
# Flujo de RESERVA de parcelas, FIEL a Testarossa.
#   cemetery.reservation.type <- tabla `tipos_reservas`
#   cemetery.reservation      <- tablas `reserva_inventario` + `reserva_ubicaciones`
#
# Ciclo de vida de la parcela (property.details.stage):
#   available -> booked (reservada) -> sold (vendida) / occupied (con inhumado)
# Si la reserva vence o se cancela, la parcela vuelve a 'available'.

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class CemeteryReservationType(models.Model):
    """Tipo de reserva (Testarossa: tabla `tipos_reservas`).

    Seed real de Testarossa:
      1 = Abono    (requiere abono, 48 horas)
      2 = Horas    (720 horas = 30 días)
      3 = Gerencia (requiere aprobación de gerencia, sin límite de horas)
    """
    _name = 'cemetery.reservation.type'
    _description = 'Tipo de Reserva'
    _order = 'name'

    name = fields.Char(string='Descripción', required=True, translate=True)
    code = fields.Char(string='Código', help='id_reserva en Testarossa')
    requires_deposit = fields.Boolean(
        string='Requiere Abono', help='abono en Testarossa')
    duration_hours = fields.Integer(
        string='Duración (horas)', help='horas en Testarossa. 0 = sin límite')
    requires_management_approval = fields.Boolean(
        string='Requiere Aprobación de Gerencia', help='gerencia en Testarossa')
    active = fields.Boolean(string='Activo', default=True)


class CemeteryReservation(models.Model):
    """Reserva de parcelas: bloquea inventario temporalmente antes de la venta."""
    _name = 'cemetery.reservation'
    _description = 'Reserva de Parcela'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='No. Reserva', required=True, copy=False, readonly=True,
        index=True, default=lambda self: _('Nuevo'))
    reservation_type_id = fields.Many2one(
        'cemetery.reservation.type', string='Tipo de Reserva', required=True,
        tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Cliente', required=True, tracking=True,
        help='id_nit en Testarossa')
    commercial_id = fields.Many2one(
        'res.users', string='Comercial', default=lambda self: self.env.user,
        help='id_comercial en Testarossa')
    company_id = fields.Many2one(
        'res.company', string='Empresa', default=lambda self: self.env.company)

    plot_ids = fields.Many2many(
        'property.details', string='Parcelas Reservadas',
        domain="[('stage', 'in', ('available', 'booked'))]",
        help='reserva_ubicaciones en Testarossa')
    plot_count = fields.Integer(
        string='Parcelas', compute='_compute_plot_count', store=True)

    date_start = fields.Datetime(
        string='Fecha Inicio', default=fields.Datetime.now, tracking=True)
    date_end = fields.Datetime(
        string='Fecha Vencimiento', compute='_compute_date_end',
        store=True, readonly=False, tracking=True)
    receipt_number = fields.Char(string='No. Recibo', help='no_recibo en Testarossa')
    deposit_amount = fields.Monetary(string='Monto de Abono', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', string='Moneda')

    state = fields.Selection([
        ('draft', 'Borrador'),
        ('active', 'Activa'),
        ('expired', 'Vencida'),
        ('converted', 'Convertida en Venta'),
        ('cancelled', 'Cancelada'),
    ], string='Estado', default='draft', tracking=True, copy=False)

    note = fields.Text(string='Notas')

    @api.depends('plot_ids')
    def _compute_plot_count(self):
        for rec in self:
            rec.plot_count = len(rec.plot_ids)

    @api.depends('date_start', 'reservation_type_id')
    def _compute_date_end(self):
        for rec in self:
            if rec.date_start and rec.reservation_type_id and \
                    rec.reservation_type_id.duration_hours:
                rec.date_end = rec.date_start + timedelta(
                    hours=rec.reservation_type_id.duration_hours)
            else:
                # Tipo Gerencia (0 horas) => sin vencimiento automático
                rec.date_end = rec.date_end if rec.date_end else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'cemetery.reservation') or _('Nuevo')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Acciones de ciclo de vida
    # ------------------------------------------------------------------
    def action_activate(self):
        """Activa la reserva y BLOQUEA las parcelas (stage -> booked)."""
        for rec in self:
            if not rec.plot_ids:
                raise UserError(_('Debe seleccionar al menos una parcela para reservar.'))
            occupied = rec.plot_ids.filtered(
                lambda p: p.stage not in ('available', 'booked'))
            if occupied:
                raise UserError(_(
                    'Estas parcelas no están disponibles para reservar: %s'
                ) % ', '.join(occupied.mapped('name')))
            if rec.reservation_type_id.requires_deposit and not rec.deposit_amount:
                raise UserError(_(
                    'El tipo de reserva "%s" requiere un monto de abono.'
                ) % rec.reservation_type_id.name)
            rec.plot_ids.write({'stage': 'booked'})
            rec.state = 'active'

    def action_expire(self):
        """Vence la reserva y LIBERA las parcelas (stage -> available)."""
        for rec in self:
            rec._release_plots()
            rec.state = 'expired'

    def action_cancel(self):
        """Cancela la reserva y libera las parcelas."""
        for rec in self:
            rec._release_plots()
            rec.state = 'cancelled'

    def action_convert_to_sale(self):
        """Marca la reserva como convertida; las parcelas pasan a vendidas."""
        for rec in self:
            if rec.state != 'active':
                raise UserError(_('Solo se puede convertir una reserva activa.'))
            rec.plot_ids.write({'stage': 'sold'})
            rec.state = 'converted'

    def action_reset_draft(self):
        for rec in self:
            rec._release_plots()
            rec.state = 'draft'

    def _release_plots(self):
        """Devuelve a 'available' las parcelas que esta reserva tenía bloqueadas."""
        self.ensure_one()
        booked = self.plot_ids.filtered(lambda p: p.stage == 'booked')
        booked.write({'stage': 'available'})

    # ------------------------------------------------------------------
    # Cron: vencer reservas activas cuya fecha de vencimiento ya pasó
    # ------------------------------------------------------------------
    @api.model
    def _cron_expire_reservations(self):
        now = fields.Datetime.now()
        expired = self.search([
            ('state', '=', 'active'),
            ('date_end', '!=', False),
            ('date_end', '<', now),
        ])
        if expired:
            expired.action_expire()
