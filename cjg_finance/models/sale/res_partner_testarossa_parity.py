# -*- coding: utf-8 -*-
"""Paridad de campos res.partner ↔ Testarossa sys_personas."""

from odoo import models, fields


class ResPartnerTestarossaParity(models.Model):
    _inherit = 'res.partner'

    # === Estado civil (sys_estado_civil) ===
    civil_status = fields.Selection([
        ('1', 'Soltero/a'),
        ('2', 'Casado/a'),
        ('3', 'Divorciado/a'),
        ('4', 'Viudo/a'),
        ('5', 'De Unión Libre'),
    ], string='Estado Civil',
       help='Equivale a sys_personas.id_estado_civil.')

    # === Tipo de documento (sys_documentos_identidad) ===
    document_type = fields.Selection([
        ('1', 'Cédula'),
        ('4', 'Pasaporte'),
        ('10', 'RNC'),
    ], string='Tipo de Documento',
       help='Equivale a sys_personas.id_documento.')

    # === Clasificación (sys_clasificacion_persona) ===
    partner_classification = fields.Selection([
        ('1', 'VIP'),
        ('2', 'AAA'),
        ('3', 'A'),
        ('4', 'B'),
        ('5', 'C'),
        ('6', 'ASEG'),
    ], string='Clasificación',
       help='Equivale a sys_personas.id_clasificacion.')

    # === Clase local / extranjero ===
    partner_class = fields.Selection([
        ('1', 'Local'),
        ('2', 'Extranjero'),
    ], string='Clase',
       help='Equivale a sys_personas.id_clase.')

    # === Datos personales adicionales ===
    birth_place = fields.Char(
        string='Lugar de Nacimiento',
        help='Equivale a sys_personas.lugar_nacimiento.')
    num_children = fields.Integer(
        string='Número de Hijos',
        help='Equivale a sys_personas.numero_hijos.')
    file_number = fields.Char(
        string='Número de Expediente (Legacy)',
        size=30,
        help='Número de archivo físico en Testarossa. Equivale a sys_personas.numero_de_archivo.')

    # === Empleo ===
    employer_name = fields.Char(
        string='Empresa donde Labora',
        help='Equivale a sys_personas.empresalabora.')
    employer_nit = fields.Char(
        string='NIT de la Empresa',
        help='Equivale a sys_personas.nitempresa.')

    # === Fiscal / comprobante ===
    comprobante_type = fields.Char(
        string='Tipo de Comprobante',
        size=10,
        help='Equivale a sys_personas.tipo_comprobante.')
    comprobante_type_real = fields.Char(
        string='Tipo de Comprobante Real',
        size=10,
        help='Equivale a sys_personas.tipo_comprobante_real.')
