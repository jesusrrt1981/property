# -*- coding: utf-8 -*-
"""
Drilldown de un Abono (vista detalle de un recibo individual).
Equivalente a testarossa/.../caja/view/cliente/listado_abono_view_detail.php
(63 líneas).

El legacy mostraba un tree simple con TIPO MOVIMIENTO y MONTO, además
del header con datos del cliente. En Odoo, el modelo ``cjg.pos.payment.receipt``
tiene muchos más campos (capital, interés, mora, mantenimiento, etc.) y
se vincula con sale.credit.line (cuotas del crédito).

Este wizard:
  1. Recibe un cjg.pos.payment.receipt.id como contexto.
  2. Muestra el header con cliente, fecha, total, NCF.
  3. Muestra un tree (real) con las líneas aplicadas (cuotas pagadas):
     cuota_nro, monto, capital, interes, mora, mantenimiento, saldo.
  4. Botón "Volver" para regresar al recibo.
"""
from odoo import api, fields, models, _


class PartnerPaymentDetailWizard(models.TransientModel):
    _name = 'cjg.finance.partner.payment.detail.wizard'
    _description = 'Detalle (Drilldown) de un Abono de Cliente'
    _log_access = True

    receipt_id = fields.Many2one(
        'cjg.pos.payment.receipt', string='Recibo',
        required=True, readonly=True,
    )

    # ── Campos del header (read-only, autocompletados) ────────────────────────
    partner_id = fields.Many2one(
        'res.partner', string='Cliente',
        related='receipt_id.partner_id', readonly=True,
    )
    partner_vat = fields.Char(
        string='Cédula/RNC',
        related='receipt_id.partner_id.vat', readonly=True,
    )
    date = fields.Datetime(
        string='Fecha',
        related='receipt_id.date', readonly=True,
    )
    amount_total = fields.Float(
        string='Monto Total',
        related='receipt_id.amount_total', readonly=True,
    )
    amount_paid = fields.Float(
        string='Monto Pagado',
        related='receipt_id.amount_paid', readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', string='Moneda',
        related='receipt_id.currency_id', readonly=True,
    )
    document_name = fields.Char(
        string='Documento',
        related='receipt_id.document_name', readonly=True,
    )
    movement_type = fields.Char(
        string='Tipo Movimiento',
        related='receipt_id.movement_type', readonly=True,
        help='SPRINT COBROS-CRITICOS 2026-06-20: fix tipo. Antes era Selection(related=...) '
             'pero pos_payment_receipt.movement_type es Char. Cambiado a Char para evitar '
             'TypeError al upgrade del módulo.',
    )
    serie = fields.Selection(
        string='Serie',
        related='receipt_id.serie', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Compañía',
        related='receipt_id.company_id', readonly=True,
    )
    state = fields.Selection(
        string='Estado',
        related='receipt_id.state', readonly=True,
    )
    # NCF (si el recibo tiene factura asociada)
    ncf = fields.Char(
        string='NCF', compute='_compute_ncf',
    )
    # Total aplicado en líneas
    total_lines_amount = fields.Float(
        string='Total Aplicado', compute='_compute_total_lines',
    )
    # Conteo de líneas
    line_count = fields.Integer(
        string='# Líneas', compute='_compute_total_lines',
    )
    # Líneas del detalle (compute desde receipt_id)
    line_ids = fields.One2many(
        'cjg.finance.partner.payment.detail.wizard.line',
        'wizard_id',
        string='Líneas del Detalle',
    )

    @api.depends('receipt_id.invoice_id.l10n_latam_document_number')
    def _compute_ncf(self):
        for wiz in self:
            ncf = False
            if wiz.receipt_id.invoice_id:
                ncf = getattr(
                    wiz.receipt_id.invoice_id, 'l10n_latam_document_number', False
                )
            wiz.ncf = ncf or ''

    @api.depends('line_ids')
    def _compute_total_lines(self):
        for wiz in self:
            wiz.total_lines_amount = sum(wiz.line_ids.mapped('monto'))
            wiz.line_count = len(wiz.line_ids)

    # ── Cargar líneas al instanciar ───────────────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        receipt_id = res.get('receipt_id') or self._context.get('default_receipt_id') \
            or self._context.get('active_id')
        if receipt_id:
            res['receipt_id'] = receipt_id
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._load_payment_lines()
        return records

    def _load_payment_lines(self):
        """Crea las líneas del wizard a partir del recibo."""
        self.ensure_one()
        Line = self.env['cjg.finance.partner.payment.detail.wizard.line']
        # Limpia líneas existentes
        self.line_ids.unlink()
        for idx, line_data in enumerate(self._get_payment_lines(), 1):
            Line.create({
                'wizard_id': self.id,
                'sequence': idx,
                'cuota_nro': line_data['cuota_nro'],
                'monto': line_data['monto'],
                'capital': line_data.get('capital', 0.0),
                'interes': line_data.get('interes', 0.0),
                'mora': line_data.get('mora', 0.0),
                'mantenimiento': line_data.get('mantenimiento', 0.0),
                'saldo': line_data.get('saldo', 0.0),
                'movement_label': line_data.get('movement_label', ''),
            })

    def _get_payment_lines(self):
        """Obtiene las líneas aplicadas a este recibo.

        Prioridad de fuente:
          1. ``credit_payment_lines`` del credit payment (cuotas pagadas)
          2. ``pos_payment_line_ids`` (líneas POS)
          3. Fallback: 1 línea con el monto del recibo
        """
        self.ensure_one()
        receipt = self.receipt_id
        if not receipt:
            return []

        lines = []

        # Intentar obtener las líneas vía sale.credit.payment
        # FIX 2026-06-17: 'pos_payment_receipt_ids' es un campo de crm.lead,
        # NO de sale.credit.payment. El vinculo correcto es el campo
        # Many2one 'sale_credit_payment_id' que el recibo POS expone
        # (cjg_finance/models/pos_payment_receipt_ext.py:22). Si ese
        # campo está vacío, intentar caer al credit_id del recibo.
        credit_payment = receipt.sale_credit_payment_id
        if not credit_payment and receipt.credit_id:
            credit_payment = self.env['sale.credit.payment'].sudo().search([
                ('credit_id', '=', receipt.credit_id.id),
                ('amount_paid', '=', receipt.amount_paid),
            ], limit=1, order='date desc, id desc')
        if not credit_payment:
            credit_payment = self.env['sale.credit.payment'].sudo().search([
                ('id', '=', False),  # búsqueda vacía explícita
            ], limit=1)

        if credit_payment and hasattr(credit_payment, 'credit_payment_lines'):
            for idx, line in enumerate(credit_payment.credit_payment_lines, 1):
                if line.state == 'cancelled':
                    continue
                credit_line = line.credit_line_id
                cuota_nro = (
                    credit_line.installment_number
                    if credit_line and hasattr(credit_line, 'installment_number')
                    else idx
                )
                lines.append({
                    'cuota_nro': cuota_nro,
                    'monto': line.amount_paid or 0.0,
                    'capital': line.amount_capital or 0.0,
                    'interes': line.amount_interest or 0.0,
                    'mora': line.amount_late_fee or 0.0,
                    'mantenimiento': (
                        line.amount_maintenance
                        if hasattr(line, 'amount_maintenance') else 0.0
                    ),
                    'saldo': (
                        credit_line.amount_pending
                        if credit_line and hasattr(credit_line, 'amount_pending')
                        else 0.0
                    ),
                })

        # Si no hay líneas de crédito, intentar vía pos_payment_line_ids
        if not lines and credit_payment and hasattr(credit_payment, 'pos_payment_line_ids'):
            for idx, line in enumerate(credit_payment.pos_payment_line_ids, 1):
                if line.state == 'cancelled':
                    continue
                lines.append({
                    'cuota_nro': idx,
                    'monto': line.amount_paid or 0.0,
                    'capital': line.amount_capital or 0.0,
                    'interes': line.amount_interest or 0.0,
                    'mora': line.amount_late_fee or 0.0,
                    'mantenimiento': 0.0,
                    'saldo': (
                        line.amount_pending
                        if hasattr(line, 'amount_pending') else 0.0
                    ),
                })

        # Si aún no hay líneas, crear al menos 1 línea con el monto del recibo
        if not lines and receipt.amount_paid > 0:
            movement_label = receipt.movement_type or '—'
            lines.append({
                'cuota_nro': 1,
                'monto': receipt.amount_paid,
                'capital': receipt.amount_capital or 0.0,
                'interes': receipt.amount_interest or 0.0,
                'mora': receipt.amount_late_fee or 0.0,
                'mantenimiento': receipt.amount_maintenance or 0.0,
                'saldo': receipt.amount_pending or 0.0,
                'movement_label': movement_label,
            })

        return lines

    def action_back(self):
        """Vuelve al recibo."""
        self.ensure_one()
        return {
            'name': _('Recibo — %s') % (self.receipt_id.name or ''),
            'type': 'ir.actions.act_window',
            'res_model': 'cjg.pos.payment.receipt',
            'view_mode': 'form',
            'res_id': self.receipt_id.id,
        }


class PartnerPaymentDetailWizardLine(models.TransientModel):
    _name = 'cjg.finance.partner.payment.detail.wizard.line'
    _description = 'Línea del Detalle de Abono'
    _order = 'wizard_id, sequence, id'

    wizard_id = fields.Many2one(
        'cjg.finance.partner.payment.detail.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Secuencia')
    cuota_nro = fields.Integer(string='Cuota Nro.')
    monto = fields.Float(string='Monto')
    capital = fields.Float(string='Capital')
    interes = fields.Float(string='Interés')
    mora = fields.Float(string='Mora')
    mantenimiento = fields.Float(string='Mantenimiento')
    saldo = fields.Float(string='Saldo')
    movement_label = fields.Char(string='Tipo Movimiento')
    currency_id = fields.Many2one(
        'res.currency', string='Moneda',
        related='wizard_id.currency_id',
    )
