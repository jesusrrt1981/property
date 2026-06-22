# -*- coding: utf-8 -*-
"""Paridad de campos sale.credit ↔ Testarossa contratos.

Solo agrega campos que NO existen en otras extensiones de sale.credit.
Verificado en /tmp/sale_credit_real_fields.txt — los demás ya están cubiertos
por cjg_finance, cjg_finance_crm, cjg_finance_contracts, etc.
"""

from odoo import models, fields


class SaleCreditTestarossaParity(models.Model):
    _inherit = 'sale.credit'

    # === Fiscal / impositivo (Testarossa: porc_impuesto, impuesto, impuesto_pagado) ===
    tax_percent = fields.Float(
        string='% Impuesto (ITBIS)',
        digits=(20, 4),
        help='Tasa de ITBIS aplicada al contrato. Equivale a contratos.porc_impuesto.')
    tax_amount = fields.Float(
        string='Monto Impuesto',
        digits=(20, 4),
        help='ITBIS calculado del contrato. Equivale a contratos.impuesto.')
    tax_paid = fields.Float(
        string='Impuesto Pagado',
        digits=(20, 4),
        help='ITBIS acumulado pagado. Equivale a contratos.impuesto_pagado.')

    # === Anulación cruzada (Testarossa: anul_por_serie_contrato + anul_por_no_contrato) ===
    annulled_by_credit_id = fields.Many2one(
        'sale.credit',
        string='Anulado por Contrato',
        help='Contrato que reemplaza/anula este. Equivale a contratos.anul_por_serie_contrato + anul_por_no_contrato.')

    # === Próximos cambios de oficial (Testarossa: nit_proximo_oficial / motorizado) ===
    next_oficial_id = fields.Many2one(
        'res.users',
        string='Próximo Oficial',
        help='Oficial que tomará el contrato en el próximo cambio. Equivale a contratos.nit_proximo_oficial.')
    next_motorista_id = fields.Many2one(
        'res.partner',
        string='Próximo Motorizado',
        domain="[('is_motorista','=',True)]",
        help='Motorizado que tomará el contrato en el próximo cambio. Equivale a contratos.nit_proximo_motorizado.')

    # === Contabilidad / facturación ===
    account_code = fields.Char(
        string='Código Contable',
        size=20,
        help='Código contable asociado al contrato. Equivale a contratos.codigo_cta.')
    billing_partner_id = fields.Many2one(
        'res.partner',
        string='Cliente Facturar',
        help='Cliente al que se factura (cuando es distinto del titular). Equivale a contratos.id_nit_facturar.')

    # === Plan financiero / situación / tipo ingreso ===
    financial_plan = fields.Selection([
        ('0', 'Plan 0 - Estándar'),
        ('1', 'Plan 1'),
        ('2', 'Plan 2'),
        ('3', 'Plan 3'),
        ('4', 'Plan 4'),
        ('5', 'Plan 5'),
        ('6', 'Plan 6'),
        ('7', 'Plan 7'),
        ('8', 'Plan 8'),
        ('9', 'Plan 9'),
    ], string='Plan Financiero',
       help='Plan financiero aplicado. Equivale a contratos.plan.')
    situacion = fields.Selection([
        ('PRE', 'Pre-necesidad'),
        ('NSD', 'Necesidad'),
    ], string='Situación',
       help='Tipo de necesidad. Equivale a contratos.situacion.')
    income_type = fields.Selection([
        ('NUEVO', 'Nuevo'),
        ('REACTIVADO', 'Reactivado'),
        ('MEJORA', 'Mejora'),
    ], string='Tipo de Ingreso',
       help='Equivale a contratos.tipo_ingreso.')
    sales_channel = fields.Integer(
        string='Canal de Venta',
        help='Canal por el que ingresó el contrato. Equivale a contratos.canal.')

    # === Bloqueo / correspondencia ===
    is_blocked = fields.Boolean(
        string='Bloqueado',
        help='Contrato bloqueado manualmente. Equivale a contratos.bloqueado.')
    correspondence = fields.Char(
        string='Correspondencia',
        size=1,
        help='Marca de correspondencia. Equivale a contratos.correspondencia.')

    # === Reiteración ===
    reiterator_partner_id = fields.Many2one(
        'res.partner',
        string='Reiterador',
        help='Partner que reiteró el contrato. Equivale a contratos.id_nit_reiterador.')
    reiterated_date = fields.Datetime(
        string='Fecha Reiterado',
        help='Equivale a contratos.fecha_reiterado.')

    # === Fechas operativas faltantes ===
    cancellation_date = fields.Date(
        string='Fecha de Cancelación',
        help='Fecha en que el contrato fue anulado/desistido (distinto de closed_date que es saldado). '
             'Equivale a contratos.fecha_cancelacion.')
    first_payment_date = fields.Date(
        string='Fecha Primer Pago',
        help='Fecha programada del primer pago. Equivale a contratos.fecha_primer_pago.')
    capital_payment_date = fields.Date(
        string='Fecha Último Abono Capital',
        help='Equivale a contratos.fecha_abono_capital.')
    print_date = fields.Date(
        string='Fecha de Impresión',
        help='Fecha en que se imprimió el contrato. Equivale a contratos.fecha_impresion.')

    # === Capital y porcentajes ===
    improvement_capital = fields.Float(
        string='Capital por Mejora',
        digits=(10, 2),
        help='Capital agregado por mejora de producto. Equivale a contratos.capital_por_mejora.')
    discount_percent = fields.Float(
        string='% Descuento',
        digits=(20, 4),
        help='% de descuento aplicado. Equivale a contratos.porc_descuento.')
    initial_percent = fields.Float(
        string='% Enganche',
        digits=(20, 4),
        help='% de enganche del contrato. Equivale a contratos.porc_enganche.')
    installment_interest = fields.Float(
        string='Interés por Cuota',
        digits=(20, 4),
        help='Interés por cuota. Equivale a contratos.interes_cuota.')

    # === Operativo / auditoría ===
    closing_periods = fields.Integer(
        string='Períodos de Cierre',
        help='Cantidad de períodos para cierre. Equivale a contratos.periodos_cierre.')
    registered_by_user_id = fields.Many2one(
        'res.users',
        string='Ingresado Por',
        help='Usuario que registró el contrato. Equivale a contratos.id_nit_ingreso.')
    product_count_legacy = fields.Integer(
        string='# Productos (Legacy)',
        help='Cantidad de productos en el contrato según Testarossa. Equivale a contratos.no_productos.')

    # === Débito automático (referencias técnicas Testarossa) ===
    legacy_card_ref = fields.Integer(
        string='Ref. Tarjeta (Legacy)',
        help='Referencia interna a la tarjeta para débito automático en Testarossa. '
             'Equivale a contratos.tarjeta_pesona. Convertir a relación cuando se modele el medio de cobro.')
    legacy_bank_account_ref = fields.Integer(
        string='Ref. Cuenta Bancaria (Legacy)',
        help='Referencia interna a la cuenta bancaria para débito automático en Testarossa. '
             'Equivale a contratos.cta_persona. Convertir a relación cuando se modele el medio de cobro.')
