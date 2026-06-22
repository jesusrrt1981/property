# -*- coding: utf-8 -*-
"""Paridad de campos sale.credit.payment ↔ Testarossa movimiento_contrato."""

from odoo import models, fields


class SaleCreditPaymentParity(models.Model):
    _inherit = 'sale.credit.payment'

    # === Identificador legacy ===
    legacy_mov_id = fields.Integer(
        string='ID Movimiento (Legacy)',
        help='ID_MOV_C de movimiento_contrato. Referencia cruzada con Testarossa.')

    # === Desglose de importes pagados en este movimiento ===
    amount_tax_paid = fields.Float(
        string='ITBIS Pagado',
        digits=(16, 4),
        help='Porción de ITBIS pagada en este movimiento. Equivale a IMPUESTO_PAG.')
    amount_maintenance = fields.Float(
        string='Monto Mantenimiento',
        digits=(16, 4),
        help='Porción de mantenimiento pagada. Equivale a MANTENIMIENTO.')
    amount_penalty = fields.Float(
        string='Monto Penalidad',
        digits=(16, 4),
        help='Penalidad pagada en este movimiento. Equivale a PENALIDAD_PAG.')

    # === Referencia a cuota ===
    installment_number = fields.Integer(
        string='Número de Cuota',
        help='Número de cuota asociada a este pago. Equivale a NO_CUOTA.')
    is_initial_payment = fields.Boolean(
        string='Es Enganche',
        help='Indica si este pago corresponde al enganche inicial. Equivale a INICIAL.')

    # === Personal de cobro ===
    collection_officer_nit = fields.Char(
        string='NIT Oficial de Cobro',
        size=20,
        help='NIT del oficial que gestionó el cobro. Equivale a OF_COBROS.')
    motorizado_nit = fields.Char(
        string='NIT Motorizado',
        size=20,
        help='NIT del motorizado que realizó el cobro. Equivale a MOTORIZADO.')

    # === Referencia de factura ===
    invoice_serie = fields.Char(
        string='Serie Factura',
        size=10,
        help='Serie de la factura fiscal asociada. Equivale a SERIE_FACTURA.')
    invoice_number = fields.Char(
        string='Número Factura',
        size=20,
        help='Número de la factura fiscal. Equivale a NO_FACTURA.')
    invoice_date = fields.Date(
        string='Fecha Factura',
        help='Fecha de la factura fiscal. Equivale a FECHA_FACTURA.')
