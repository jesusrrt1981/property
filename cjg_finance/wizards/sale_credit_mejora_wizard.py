# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class SaleCreditMejoraWizard(models.TransientModel):
    _name = 'sale.credit.mejora.wizard'
    _description = 'Wizard de Mejora de Producto'

    credit_id = fields.Many2one(
        'sale.credit',
        string='Contrato Origen',
        required=True,
        readonly=True,
    )
    current_product_id = fields.Many2one(
        'product.product',
        related='credit_id.product_id',
        string='Producto Actual',
        readonly=True,
    )
    current_product_price = fields.Float(
        related='credit_id.product_id.lst_price',
        string='Precio Producto Actual',
        readonly=True,
    )
    current_product_type = fields.Selection(
        related='credit_id.process_product_type',
        string='Tipo Producto Actual',
        readonly=True,
    )
    new_product_id = fields.Many2one(
        'product.product',
        string='Nuevo Producto',
        domain="[('sale_ok', '=', True)]",
        required=True,
    )
    new_product_type = fields.Selection(
        string='Tipo Producto Nuevo',
        selection=[('property', 'Propiedad'), ('service', 'Servicio Funerario')],
        compute='_compute_new_product_type',
    )
    new_product_price = fields.Monetary(
        string='Precio del Nuevo Producto',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
    )
    discount_amount = fields.Monetary(
        string='Descuento Autorizado',
        currency_field='currency_id',
        default=0.0,
        help='Descuento aplicado DESPUÉS de restar el capital pagado, según el documento '
             'Proceso reactivacion y Mejora (párrafo: "luego de esto es que se realizan '
             'los descuentos de lugar").',
    )
    capital_paid = fields.Monetary(
        string='Capital Pagado (100% del capital, sin intereses)',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
        help='Solo se considera el 100% del capital pagado. No se considera el interés '
             'pagado, según el documento de Mejora de Producto.',
    )
    precio_neto_nuevo = fields.Monetary(
        string='Precio Neto Nuevo',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
        help='Precio del nuevo producto menos el descuento autorizado. '
             'Es la base sobre la cual se calcula el completivo del inicial.',
    )
    completivo_inicial = fields.Monetary(
        string='Completivo del Inicial',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
        help='Diferencia entre el precio neto del nuevo producto y el capital pagado. '
             'Si es positivo: el cliente debe pagar la diferencia. '
             'Si es cero: el cliente solo firma el cambio. '
             'Si el capital pagado excede el nuevo precio, el resultado es cero y el '
             'excedente aparece como Saldo a Favor.',
    )
    saldo_a_favor = fields.Monetary(
        string='Saldo a Favor',
        currency_field='currency_id',
        compute='_compute_amounts',
        readonly=True,
        help='Si el capital pagado excede el nuevo precio neto, el cliente tiene saldo a '
             'favor que debe ser aceptado o requerir aprobación de gerencia.',
    )
    accept_saldo_favor = fields.Boolean(
        string='Aceptar Saldo a Favor',
        default=False,
        help='Marque esta casilla si el cliente ACEPTA el saldo a favor (o si gerencia '
             'lo ha autorizado). Es obligatorio cuando el capital pagado excede el nuevo '
             'precio neto.',
    )
    overdue_installments = fields.Integer(
        string='Cuotas Vencidas',
        compute='_compute_amounts',
        readonly=True,
        help='Cantidad de cuotas no pagadas cuya fecha esperada es anterior a hoy. '
             'Debe ser cero (o el contrato estar saldado) para proceder con la mejora.',
    )
    is_al_dia = fields.Boolean(
        string='¿Al Día en Pagos?',
        compute='_compute_amounts',
        readonly=True,
        help='True si el cliente no tiene cuotas vencidas O si ha saldado la inversión.',
    )
    notes = fields.Text(string='Observaciones')
    currency_id = fields.Many2one(
        'res.currency',
        related='credit_id.currency_id',
        readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        credit = self.env['sale.credit'].browse(
            self.env.context.get('active_id') or values.get('credit_id')
        )
        if credit and credit.exists():
            values.setdefault('credit_id', credit.id)
        return values

    @api.depends('new_product_id', 'credit_id')
    def _compute_new_product_type(self):
        for wizard in self:
            wizard.new_product_type = False
            if not wizard.new_product_id or not wizard.credit_id:
                continue
            # Heredamos la misma heurística que _get_process_product_type del
            # contrato origen: si el nuevo producto comparte la categoría del
            # producto del contrato origen, se considera del mismo tipo.
            old_type = wizard.current_product_type
            if not old_type:
                continue
            old_categ = wizard.credit_id.product_id.categ_id if wizard.credit_id.product_id else False
            new_categ = wizard.new_product_id.categ_id
            if old_categ and new_categ and old_categ == new_categ:
                wizard.new_product_type = old_type

    @api.depends('credit_id', 'new_product_id', 'discount_amount')
    def _compute_amounts(self):
        for wizard in self:
            credit = wizard.credit_id
            # 1) Capital pagado (SOLO CAPITAL, no intereses, según doc)
            capital = credit.process_capital_paid or 0.0 if credit else 0.0
            wizard.capital_paid = capital

            # 2) Precio del nuevo producto
            if wizard.new_product_id:
                price = wizard.new_product_id.lst_price or 0.0
                wizard.new_product_price = price
                # 3) Precio neto = precio nuevo - descuento
                #    (descuentos se aplican DESPUÉS, según el documento legacy)
                wizard.precio_neto_nuevo = price - (wizard.discount_amount or 0.0)
                # 4) Completivo = max(0, precio_neto - capital_pagado)
                wizard.completivo_inicial = max(0.0, wizard.precio_neto_nuevo - capital)
                # 5) Saldo a favor = max(0, capital_pagado - precio_neto)
                wizard.saldo_a_favor = max(0.0, capital - wizard.precio_neto_nuevo)
            else:
                wizard.new_product_price = 0.0
                wizard.precio_neto_nuevo = 0.0
                wizard.completivo_inicial = 0.0
                wizard.saldo_a_favor = 0.0

            # 6) Cuotas vencidas y "al día" (al día = sin vencidas O saldado)
            wizard.overdue_installments = 0
            wizard.is_al_dia = False
            if credit:
                today = fields.Date.context_today(wizard)
                wizard.overdue_installments = len(credit.credit_lines.filtered(
                    lambda l: l.state not in ('paid', 'cancelled')
                    and l.expected_date_payment
                    and l.expected_date_payment < today
                ))
                saldado = (credit.credit_Adeudado or 0.0) <= 0.0
                wizard.is_al_dia = (wizard.overdue_installments == 0) or saldado

    def _validate_eligibility(self):
        """Replica las validaciones del documento Proceso reactivacion y Mejora:

        - Cliente debe estar al día O haber saldado su inversión
        - Producto mejorado debe ser del mismo tipo (Parcela o Servicio Funerario)
        - Producto mejorado debe ser superior en precio y categoría
        - Se considera solo el 100% del capital pagado (no los intereses)
        """
        self.ensure_one()
        credit = self.credit_id

        # 1) Estado del contrato
        if credit.state not in ('approved', 'active', 'closed'):
            raise UserError(_(
                'El contrato %s no es elegible para mejora. '
                'Solo contratos en estado Aprobado, Activo o Saldado pueden mejorar. '
                'Estado actual: %s'
            ) % (credit.name, credit.state))

        # 2) Al día en pagos O saldado (validación crítica del documento)
        saldado = (credit.credit_Adeudado or 0.0) <= 0.0
        if self.overdue_installments > 0 and not saldado:
            raise UserError(_(
                'El contrato %s tiene %d cuota(s) vencida(s) y capital pendiente (%s). '
                'Para realizar una mejora, el cliente debe estar AL DÍA en sus pagos '
                'o haber SALDADO su inversión, según el documento '
                '"Proceso reactivacion y Mejora".'
            ) % (credit.name, self.overdue_installments, credit.credit_Adeudado or 0.0))

        # 3) Capital pagado debe ser > 0 (no se permite mejora sin capital)
        if (credit.process_capital_paid or 0.0) <= 0.0:
            raise UserError(_(
                'El contrato %s no tiene capital pagado disponible para una mejora. '
                'Se considera solo el 100% del capital pagado, no los intereses.'
            ) % (credit.name,))

        # 4) Mismo tipo de producto (Parcela→Parcela o Servicio→Servicio)
        if self.new_product_id and credit.product_id:
            new_type = self.new_product_type
            old_type = self.current_product_type
            if new_type and old_type and new_type != old_type:
                raise ValidationError(_(
                    'El producto mejorado debe ser del MISMO TIPO que el adquirido '
                    'inicialmente (%s → %s). '
                    'Ej. Mejorar Jardín trinitaria a Jardín de Familias (Parcela → '
                    'Parcela) o Servicio Confort a un Servicio Elegance '
                    '(Servicio → Servicio).'
                ) % (old_type, new_type))

        # 5) Precio del nuevo producto debe ser mayor (categoría y precio)
        if self.new_product_id and credit.product_id:
            if (self.new_product_id.lst_price or 0.0) <= (credit.product_id.lst_price or 0.0):
                raise ValidationError(_(
                    'El producto mejorado debe ser SUPERIOR en precio al adquirido '
                    'inicialmente. Precio actual: %s. Precio nuevo: %s.'
                ) % (credit.product_id.lst_price, self.new_product_id.lst_price))

        # 6) Si hay saldo a favor, debe estar aceptado
        if self.saldo_a_favor > 0 and not self.accept_saldo_favor:
            raise UserError(_(
                'El capital pagado (%s) excede el nuevo precio neto (%s). '
                'Saldo a favor: %s. '
                'El cliente debe ACEPTAR el saldo a favor o requerir aprobación de '
                'gerencia para proceder con la mejora.'
            ) % (self.capital_paid, self.precio_neto_nuevo, self.saldo_a_favor))

    def action_confirm_mejora(self):
        """Create CRM lead for improvement process.

        El flujo es:
          wizard → crm.lead (improvement) → al confirmar pago → sale.credit
          (derivado con origin_credit_id) → el contrato viejo se marca
          automáticamente como 'anulado_mejora' en
          portal_crm_to_quotation/models/crm.py:_create_contract_from_payments.
        """
        self.ensure_one()
        self._validate_eligibility()

        credit = self.credit_id
        capital_paid = credit.process_capital_paid or 0.0

        # Create CRM lead for improvement
        # precio_neto_nuevo = final_price del lead (precio nuevo - descuento)
        # completivo_inicial = initial_payment del lead (lo que cliente debe pagar)
        # saldo_a_favor = informativo (queda como observación / requiere acción manual)
        # IMPORTANTE: apply_discounts=False garantiza que el compute _compute_discounts
        # use la fórmula del documento legacy: final_price = price_dop - discount_amount
        # (sin políticas por nivel), ya que el descuento de mejora YA está cuantificado.
        lead_vals = {
            'name': _('Mejora: %s → %s') % (credit.name, self.new_product_id.name),
            'partner_id': credit.partner_id.id,
            'contract_process_type': 'improvement',
            'origin_sale_credit_id': credit.id,
            'capitalized_amount': capital_paid,
            'price_dop': self.new_product_price or 0.0,
            'apply_discounts': False,
            'discount_manual_amount': self.discount_amount or 0.0,
            'final_price': self.precio_neto_nuevo,
            'initial_payment': self.completivo_inicial,
            'product_type': self.new_product_type or self.current_product_type or False,
        }
        # Para servicios funerarios: asignar funeral_service_id (product.template)
        # Para propiedades: la lógica de subproyecto requiere property_product_ids,
        # que no es un mapeo 1-a-1 desde product.product; se delega al flujo
        # existente de creación de contrato.
        if self.new_product_id and self.new_product_type == 'service':
            template = self.new_product_id.product_tmpl_id
            if template:
                lead_vals['funeral_service_id'] = template.id
        if self.notes:
            lead_vals['description'] = self.notes

        lead = self.env['crm.lead'].create(lead_vals)

        credit.message_post(
            body=_(
                '<p><strong>Proceso de mejora de producto iniciado.</strong></p>'
                '<ul>'
                '<li>Producto origen: %s (precio %s)</li>'
                '<li>Producto nuevo: %s (precio %s)</li>'
                '<li>Descuento autorizado: %s</li>'
                '<li>Precio neto nuevo: %s</li>'
                '<li>Capital pagado (100%%, sin intereses): %s</li>'
                '<li>Completivo del inicial: %s</li>'
                '<li>Saldo a favor: %s%s</li>'
                '<li>Cuotas vencidas al inicio: %s</li>'
                '<li>Estado al día: %s</li>'
                '</ul>'
                '<p>Planilla CRM creada: '
                '<a href="#id=%d&model=crm.lead">%s</a></p>'
                '<p><em>El contrato viejo se marcará como ANULADO POR MEJORA al '
                'confirmarse el pago del completivo en la planilla CRM, según el '
                'documento "Proceso reactivacion y Mejora".</em></p>'
            ) % (
                credit.product_id.name if credit.product_id else 'N/A',
                self.current_product_price or 0.0,
                self.new_product_id.name,
                self.new_product_price,
                self.discount_amount or 0.0,
                self.precio_neto_nuevo,
                capital_paid,
                self.completivo_inicial,
                self.saldo_a_favor,
                ' (ACEPTADO)' if self.accept_saldo_favor and self.saldo_a_favor > 0 else '',
                self.overdue_installments,
                'Sí' if self.is_al_dia else 'No',
                lead.id, lead.name,
            )
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Planilla de Mejora'),
            'res_model': 'crm.lead',
            'res_id': lead.id,
            'view_mode': 'form',
            'target': 'current',
        }
