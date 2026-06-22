# -*- coding: utf-8 -*-

from odoo import models, fields, api

class ResCompany(models.Model):
    """
    Extensión de res.company para configuración de cuentas contables
    por tipo de servicio y empresa
    """
    _inherit = 'res.company'
    
    # ID de empresa en Testarossa (para migración)
    testarossa_em_id = fields.Integer(
        string='ID Empresa Testarossa',
        help='ID de empresa en el sistema legacy Testarossa (campo em_id)'
    )

    receipt_sequence_prefix = fields.Char(
        string='Prefijo de Recibos',
        size=20,
        help='Prefijo para la numeración de recibos de esta empresa (ej. REC-JM-, REC-CM-). '
             'Si está vacío, se usa REC-.',
    )
    
    # ===== CUENTAS CONTABLES POR TIPO DE SERVICIO =====
    
    # Cuentas de Caja por servicio
    pf_cash_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Caja PF',
        domain="[('account_type', '=', 'asset_cash'), ('company_id', '=', id)]",
        help='Cuenta de caja para servicios de Preventa Funeraria'
    )
    
    cm_cash_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Caja CM',
        domain="[('account_type', '=', 'asset_cash'), ('company_id', '=', id)]",
        help='Cuenta de caja para servicios de Cementerio/Mausoleo'
    )
    
    cre_cash_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Caja CRE',
        domain="[('account_type', '=', 'asset_cash'), ('company_id', '=', id)]",
        help='Cuenta de caja para servicios de Cremación'
    )
    
    # Diarios contables por servicio
    pf_journal_id = fields.Many2one(
        'account.journal',
        string='Diario PF',
        domain="[('type', '=', 'cash'), ('company_id', '=', id)]",
        help='Diario para pagos de Preventa Funeraria'
    )
    
    cm_journal_id = fields.Many2one(
        'account.journal',
        string='Diario CM',
        domain="[('type', '=', 'cash'), ('company_id', '=', id)]",
        help='Diario para pagos de Cementerio/Mausoleo'
    )
    
    cre_journal_id = fields.Many2one(
        'account.journal',
        string='Diario Cremación',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', id)]"
    )
    
    # Servicio Funerario (SF)
    sf_cash_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Caja SF',
        domain="[('account_type', '=', 'asset_cash'), ('company_id', '=', id)]",
        help='Cuenta de caja para Servicios Funerarios'
    )
    sf_journal_id = fields.Many2one(
        'account.journal',
        string='Diario SF',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', id)]"
    )
    sf_income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Ingreso SF',
        domain="[('account_type', '=', 'income'), ('company_id', '=', id)]"
    )
    
    # Cuentas de ingreso por servicio
    pf_income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Ingreso PF',
        domain="[('account_type', '=', 'income'), ('company_id', '=', id)]",
        help='Cuenta de ingreso para servicios de Preventa Funeraria'
    )
    
    cm_income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Ingreso CM',
        domain="[('account_type', '=', 'income'), ('company_id', '=', id)]",
        help='Cuenta de ingreso para servicios de Cementerio/Mausoleo'
    )
    
    cre_income_account_id = fields.Many2one(
        'account.account',
        string='Cuenta Ingreso CRE',
        domain="[('account_type', '=', 'income'), ('company_id', '=', id)]",
        help='Cuenta de ingreso para servicios de Cremación'
    )
