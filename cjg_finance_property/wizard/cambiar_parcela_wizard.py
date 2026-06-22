# -*- coding: utf-8 -*-
"""
Wizard para cambiar la parcela asignada a un contrato (Mejora de Parcela).

Replica el flujo legacy de testarossa/modulos/contratos/class/class.Contratos.php::cambiarProducto
en un solo wizard que:

  1. Valida que el contrato esté activo y la misma empresa.
  2. Valida que la parcela nueva esté disponible.
  3. Libera la parcela vieja (stage='available').
  4. Asigna la parcela nueva al contrato (stage='sold').
  5. Crea un cargo (ND) en el contrato por "cambio de parcela".
  6. Auditoría completa en chatter.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class CambiarParcelaWizard(models.TransientModel):
    _name = 'cambiar.parcela.wizard'
    _description = 'Cambiar Parcela (Mejora de Parcela)'
    _transient_max_hours = 1

    # === SECCIÓN 1: Contrato actual ===
    contract_id = fields.Many2one(
        'sale.credit',
        string='Contrato',
        required=True,
        domain="[('state', 'in', ('approved', 'active'))]",
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='contract_id.currency_id',
        readonly=True,
    )
    parcela_vieja_id = fields.Many2one(
        'property.details',
        string='Parcela Actual',
        help='Parcela actualmente asignada al contrato. Si el contrato '
             'tiene varias parcelas, se debe seleccionar manualmente.',
    )
    parcela_vieja_display = fields.Char(
        string='Parcela Actual (Display)',
        compute='_compute_parcela_vieja_display',
    )

    # === SECCIÓN 2: Nueva parcela ===
    parcela_nueva_id = fields.Many2one(
        'property.details',
        string='Nueva Parcela',
        required=True,
        domain="[('stage', 'in', ('available', 'booked'))]",
    )
    parcela_nueva_display = fields.Char(
        string='Nueva Parcela (Display)',
        compute='_compute_parcela_nueva_display',
    )

    # === SECCIÓN 3: Costo del cambio ===
    costo_cambio = fields.Monetary(
        string='Costo del Cambio de Parcela',
        currency_field='currency_id',
        help='Monto del cargo que se generará en el contrato. '
             'Si es 0, el cambio es gratuito (ej. corrección administrativa).',
    )
    motivo = fields.Text(
        string='Motivo del Cambio',
        required=True,
        help='Justificación escrita del cambio de parcela.',
    )

    @api.depends('parcela_vieja_id')
    def _compute_parcela_vieja_display(self):
        for wiz in self:
            if wiz.parcela_vieja_id:
                wiz.parcela_vieja_display = (
                    f"{wiz.parcela_vieja_id.block or 'N/A'}-"
                    f"{wiz.parcela_vieja_id.lot or 'N/A'}"
                )
            else:
                wiz.parcela_vieja_display = 'N/A'

    @api.depends('parcela_nueva_id')
    def _compute_parcela_nueva_display(self):
        for wiz in self:
            if wiz.parcela_nueva_id:
                wiz.parcela_nueva_display = (
                    f"{wiz.parcela_nueva_id.block or 'N/A'}-"
                    f"{wiz.parcela_nueva_id.lot or 'N/A'}"
                )
            else:
                wiz.parcela_nueva_display = 'N/A'

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        """Auto-sugerir la parcela vieja cuando se selecciona un contrato."""
        if not self.contract_id:
            self.parcela_vieja_id = False
            return
        contract = self.contract_id
        # Si el contrato tiene property_product_ids (M2M), tomar la primera
        # parcela que esté 'sold' o 'occupied' (es la que tiene el contrato)
        if hasattr(contract, 'property_product_ids') and contract.property_product_ids:
            sold_props = contract.property_product_ids.filtered(
                lambda p: p.stage in ('sold', 'occupied')
            )
            if sold_props:
                self.parcela_vieja_id = sold_props[0].id
                return
            self.parcela_vieja_id = contract.property_product_ids[0].id
            return
        # Compatibilidad: contrato con property_id (M2O)
        if hasattr(contract, 'property_id') and contract.property_id:
            self.parcela_vieja_id = contract.property_id.id

    @api.onchange('parcela_nueva_id')
    def _onchange_parcela_nueva_id(self):
        """Auto-completar el costo del cambio basado en la diferencia de jardín/fase."""
        if not self.parcela_nueva_id:
            return
        if not self.parcela_vieja_id:
            return
        misma_fase = (
            self.parcela_nueva_id.garden_id == self.parcela_vieja_id.garden_id
            and self.parcela_nueva_id.phase_id == self.parcela_vieja_id.phase_id
        )
        if misma_fase:
            # Misma fase: sin costo (es un cambio lateral legítimo)
            self.costo_cambio = 0.0
        else:
            # Fase o jardín distinto: tomar diferencia de precio como sugerencia
            try:
                precio_nueva = self.parcela_nueva_id.price or 0.0
                precio_vieja = self.parcela_vieja_id.price or 0.0
                diferencia = precio_nueva - precio_vieja
                self.costo_cambio = max(diferencia, 0.0)
            except Exception:
                self.costo_cambio = 0.0

    @api.constrains('parcela_nueva_id')
    def _check_parcela_nueva_distinct(self):
        for wiz in self:
            if wiz.parcela_vieja_id and wiz.parcela_nueva_id == wiz.parcela_vieja_id:
                raise ValidationError(_(
                    "La nueva parcela no puede ser la misma que la actual."
                ))

    def _validar_empresa(self, contract, parcela_nueva):
        """Valida que la parcela nueva pertenezca a la misma empresa que el contrato."""
        if parcela_nueva.company_id and contract.company_id and \
                parcela_nueva.company_id != contract.company_id:
            raise UserError(_(
                "La nueva parcela pertenece a '%s' pero el contrato a '%s'. "
                "Solo se puede cambiar a parcelas de la misma empresa."
            ) % (parcela_nueva.company_id.name, contract.company_id.name))

    def _liberar_parcela_vieja(self, parcela_vieja, contract, parcela_nueva):
        """Libera la parcela vieja: la marca como 'available' y limpia el booking."""
        parcela_vieja.write({
            'stage': 'available',
            'sold_booking_id': False,
        })
        parcela_vieja.message_post(body=_(
            "Parcela liberada por cambio a otra parcela. "
            "Contrato: %s. Nueva parcela: %s. "
            "Motivo: %s."
        ) % (contract.name, parcela_nueva.display_name, self.motivo))

    def _asignar_parcela_nueva(self, parcela_nueva, contract, parcela_vieja):
        """Asigna la parcela nueva: la marca como 'sold' y la vincula al booking."""
        vals_nueva = {'stage': 'sold'}
        if hasattr(parcela_nueva, 'sold_booking_id'):
            vals_nueva['sold_booking_id'] = contract.id
        parcela_nueva.write(vals_nueva)
        parcela_nueva.message_post(body=_(
            "Parcela asignada por cambio desde otro contrato. "
            "Contrato: %s. "
            "Parcela anterior liberada: %s. "
            "Motivo: %s."
        ) % (
            contract.name,
            parcela_vieja.display_name if parcela_vieja else 'N/A',
            self.motivo,
        ))

    def _actualizar_relacion_contrato(self, contract, parcela_vieja, parcela_nueva):
        """Actualiza la relación entre el contrato y las parcelas."""
        # Si el contrato usa property_product_ids (M2M)
        if hasattr(contract, 'property_product_ids'):
            if parcela_vieja and parcela_vieja in contract.property_product_ids:
                contract.write({
                    'property_product_ids': [
                        (3, parcela_vieja.id, 0),
                        (4, parcela_nueva.id, 0),
                    ],
                })
            else:
                contract.write({
                    'property_product_ids': [(4, parcela_nueva.id, 0)],
                })
        # Compatibilidad: contrato con property_id (M2O)
        if hasattr(contract, 'property_id'):
            contract.write({'property_id': parcela_nueva.id})

    def _crear_cargo_cambio(self, contract, parcela_vieja, parcela_nueva):
        """Crea un cargo (ND) en el contrato si el costo del cambio es positivo."""
        if self.costo_cambio <= 0:
            return False
        charge = self.env['sale.credit.charge'].create({
            'credit_id': contract.id,
            'charge_type': 'charge',
            'amount': self.costo_cambio,
            'reason': _(
                'Cambio de parcela: de %s a %s. '
                'Motivo: %s.'
            ) % (
                self.parcela_vieja_display,
                self.parcela_nueva_display,
                self.motivo[:200],
            ),
            'date': fields.Date.today(),
        })
        return charge

    def _post_chatter_auditoria(self, contract, parcela_vieja, parcela_nueva, charge):
        """Publica mensaje de auditoría completo en el chatter del contrato."""
        msg_lines = [
            "<strong>CAMBIO DE PARCELA (Mejora de Parcela) realizado</strong>",
            f"<ul>"
            f"<li>Parcela anterior: {self.parcela_vieja_display} "
            f"(liberada, ahora 'available')</li>"
            f"<li>Nueva parcela: {self.parcela_nueva_display} "
            f"(asignada, ahora 'sold')</li>"
            f"<li>Costo del cambio: {self.currency_id.symbol or ''}"
            f"{self.costo_cambio:,.2f}</li>"
            f"<li>Motivo: {self.motivo}</li>"
            f"</ul>",
        ]
        if charge:
            msg_lines.append(
                f"<p>Cargo generado: "
                f"<a href=\"#id={charge.id}&model=sale.credit.charge\">"
                f"{charge.name}</a> por {self.currency_id.symbol or ''}"
                f"{self.costo_cambio:,.2f}.</p>"
            )
        contract.message_post(
            body=''.join(msg_lines),
            subject=_('Mejora de Parcela'),
        )

    def action_cambiar_parcela(self):
        """Ejecuta el cambio de parcela."""
        self.ensure_one()
        if not self.parcela_nueva_id:
            raise UserError(_("Debe seleccionar la nueva parcela."))
        if not self.contract_id:
            raise UserError(_("Debe seleccionar un contrato."))

        contract = self.contract_id
        parcela_vieja = self.parcela_vieja_id
        parcela_nueva = self.parcela_nueva_id

        if contract.state not in ('approved', 'active'):
            raise UserError(_(
                "Solo se puede cambiar la parcela de contratos en estado "
                "'Aprobado' o 'Activo'. Estado actual: %s."
            ) % contract.state)

        if parcela_nueva.stage not in ('available', 'booked'):
            raise UserError(_(
                "La parcela '%s' no está disponible para asignación. "
                "Estado actual: %s."
            ) % (parcela_nueva.display_name, parcela_nueva.stage))

        self._validar_empresa(contract, parcela_nueva)

        charge = False
        with self.env.cr.savepoint():
            self._liberar_parcela_vieja(parcela_vieja, contract, parcela_nueva)
            self._asignar_parcela_nueva(parcela_nueva, contract, parcela_vieja)
            self._actualizar_relacion_contrato(contract, parcela_vieja, parcela_nueva)
            charge = self._crear_cargo_cambio(contract, parcela_vieja, parcela_nueva)
            self._post_chatter_auditoria(
                contract, parcela_vieja, parcela_nueva, charge
            )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'property.details',
            'res_id': parcela_nueva.id,
            'view_mode': 'form',
            'target': 'current',
        }
