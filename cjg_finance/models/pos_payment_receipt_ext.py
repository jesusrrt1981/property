import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PosPaymentReceipt(models.Model):
    _inherit = 'cjg.pos.payment.receipt'

    sale_credit_id = fields.Many2one('sale.credit', string='Contrato de Crédito')
    credit_line_id = fields.Many2one('sale.credit.line', string='Línea de Crédito', 
                                     domain="[('credit_id', '=', sale_credit_id)]")
    maintenance_contract_id = fields.Many2one('maintenance.contract', string='Contrato de Mantenimiento')
    
    # Alias para compatibilidad con vistas
    credit_contract_id = fields.Many2one('sale.credit', string='Contrato', 
                                         related='sale_credit_id', store=True, readonly=False)
    
    # Campos para información de RCV
    sale_credit_payment_id = fields.Many2one('sale.credit.payment', string='Pago de Crédito')
    credit_installments_pending = fields.Integer(string='Cuotas Pendientes', 
                                                  compute='_compute_credit_info')
    credit_suggested_amount = fields.Monetary(string='Monto Sugerido', 
                                              currency_field='currency_id',
                                              compute='_compute_credit_info')
    credit_total_debt = fields.Monetary(string='Deuda Total', 
                                        currency_field='currency_id',
                                        compute='_compute_credit_info')

    @api.depends('credit_contract_id', 'credit_contract_id.credit_lines')
    def _compute_credit_info(self):
        """Calcular información del contrato de crédito"""
        for receipt in self:
            if receipt.credit_contract_id:
                contract = receipt.credit_contract_id
                pending_lines = contract.credit_lines.filtered(lambda l: l.state != 'paid')
                receipt.credit_installments_pending = len(pending_lines)
                receipt.credit_suggested_amount = pending_lines[:1].amount_total if pending_lines else 0.0
                receipt.credit_total_debt = sum(pending_lines.mapped('amount_total'))
            else:
                receipt.credit_installments_pending = 0
                receipt.credit_suggested_amount = 0.0
                receipt.credit_total_debt = 0.0

    @api.depends('sale_credit_id', 'maintenance_contract_id', 'document_type')
    def _compute_document_info(self):
        super()._compute_document_info()
        for receipt in self:
            if receipt.document_type == 'credit' and receipt.sale_credit_id:
                receipt.document_name = receipt.sale_credit_id.name
                receipt.document_reference = receipt.sale_credit_id.partner_id.name
            elif receipt.document_type == 'maintenance' and receipt.maintenance_contract_id:
                receipt.document_name = receipt.maintenance_contract_id.name
                receipt.document_reference = receipt.maintenance_contract_id.partner_id.name


    def _assign_document_from_barcode(self):
        """Resolver código exacto de Testarossa también contra contratos.

        La clase base POS ya resuelve facturas y órdenes. Testarossa caja permite
        escanear/buscar la cuenta/contrato; aquí añadimos sale.credit y
        maintenance.contract sin cambiar el flujo existente.
        """
        super()._assign_document_from_barcode()
        self.ensure_one()
        if self.document_type:
            return

        barcode = (self.pos_reference or '').strip()
        if not barcode:
            return

        Credit = self.env['sale.credit'].sudo().with_context(active_test=True)
        credit = Credit.search([('name', '=', barcode)], limit=1)
        if not credit:
            compact = barcode.replace(' ', '').replace('-', '')
            if compact and compact != barcode:
                credit = Credit.search([('name', 'ilike', compact)], limit=1)
        if credit:
            line = credit.credit_lines.filtered(
                lambda l: l.active and l.state not in ('paid', 'cancelled') and l.amount_residual > 0
            ).sorted(key=lambda l: (l.expected_date_payment or fields.Date.today(), l.id))[:1]
            vals = {
                'document_type': 'credit',
                'sale_credit_id': credit.id,
                'partner_id': credit.partner_id.id,
                'company_id': credit.company_id.id,
            }
            if line:
                vals['credit_line_id'] = line.id
            self.write(vals)
            return

        if 'maintenance.contract' in self.env:
            Maintenance = self.env['maintenance.contract'].sudo().with_context(active_test=True)
            maintenance = Maintenance.search([('name', '=', barcode)], limit=1)
            if maintenance:
                self.write({
                    'document_type': 'maintenance',
                    'maintenance_contract_id': maintenance.id,
                    'partner_id': maintenance.partner_id.id,
                    'company_id': maintenance.company_id.id,
                })

    def _prepare_quick_collect_payment_vals(self):
        self.ensure_one()
        contract = self.credit_contract_id or self.sale_credit_id
        if not contract:
            raise UserError(_('Debe seleccionar un contrato antes de generar el cobro rápido.'))

        currency = contract.currency_id_money or self.company_id.currency_id or self.env.company.currency_id
        payment_method = self.payment_method_id or self.journal_id
        if not payment_method:
            raise UserError(_('El recibo debe tener un método de pago antes de generar el cobro rápido.'))

        return {
            'partner_id': self.partner_id.id,
            'credit_id': contract.id,
            'sale_credit_id': contract.id,
            'credit_line_id': self.credit_line_id.id,
            'session_id': self.session_id.id,
            'company_id': self.company_id.id,
            'currency_id': currency.id,
            'payment_method_id': payment_method.id,
            'journal_id': payment_method.id,
            'amount_total': self.amount_paid,
            'amount_paid': self.amount_paid,
            'date': self.date or fields.Datetime.now(),
            'payment_date': fields.Date.context_today(self),
            'instrument_id': self.instrument_id.id,
            'point_id': self.point_id.id,
            'collector_id': self.collector_id.id,
            'user_id': self.user_id.id or self.env.user.id,
            'payment_purpose': self.payment_purpose or 'other',
            'movement_type': self.movement_type or 'cuota',
            'document_type': 'credit',
            'notes': self.notes or _('Cobro rápido generado desde recibo POS %s') % self.name,
        }

    def action_confirm(self):
        """Confirma el recibo y, si es de tipo credit con contrato, aplica
        automaticamente el pago a las cuotas (mata la deuda del contrato).

        Antes: action_confirm dejaba el recibo en 'to_distribute' con asiento
        contable creado, pero la linea de credito (sale.credit.line) no se
        actualizaba porque action_quick_collect no se llamaba. Resultado: el
        cliente veia el dinero entrar a caja pero su cuota seguia 'pending'.
        """
        res = super().action_confirm()
        for receipt in self:
            if self.env.context.get('_skip_auto_quick_collect'):
                continue
            # `sale.credit.payment` ya distribuye sus cuotas por su propio flujo
            # (`action_post`), por lo que no debe volver a ejecutar quick collect
            # aquí o terminaría duplicando pagos.
            if receipt._name == 'sale.credit.payment':
                continue
            if receipt.sale_credit_payment_id:
                continue
            contract = receipt.credit_contract_id or receipt.sale_credit_id
            if not (receipt.document_type == 'credit' and contract and receipt.amount_paid > 0):
                continue
            try:
                receipt.with_context(_skip_auto_quick_collect=True).action_quick_collect()
            except UserError:
                raise
            except Exception as exc:
                _logger.exception(
                    "Auto quick-collect fallo para recibo %s (contrato %s)",
                    receipt.name, contract.name,
                )
                raise UserError(_(
                    "No se pudo aplicar el cobro del recibo %s al contrato %s. "
                    "La operación fue revertida: %s"
                ) % (receipt.display_name, contract.display_name, exc))
        return res

    def action_quick_collect(self):
        """Convierte un recibo con contrato en pago de crédito operativo."""
        self.ensure_one()
        if self.state == 'cancelled':
            raise UserError(_('No se puede generar cobro rápido desde un recibo cancelado.'))
        if self.amount_paid <= 0:
            raise UserError(_('El monto pagado debe ser mayor a cero.'))

        if self.sale_credit_payment_id:
            if self.state != 'distributed':
                self.state = 'distributed'
            return {
                'success': True,
                'payment_id': self.sale_credit_payment_id.id,
                'receipt_id': self.id,
            }

        if not self.move_id:
            contract = self.credit_contract_id or self.sale_credit_id
            self.write({
                'document_type': 'credit',
                'sale_credit_id': contract.id,
                'credit_line_id': self.credit_line_id.id,
                'amount_total': self.amount_paid,
            })
            if self.state == 'draft':
                self.with_context(_skip_auto_quick_collect=True).action_confirm()

        payment_vals = self._prepare_quick_collect_payment_vals()
        payment = self.env['sale.credit.payment'].create(payment_vals)
        payment.write({
            'move_id': self.move_id.id,
            'distribution_move_id': self.distribution_move_id.id,
            'intercompany_move_id': self.intercompany_move_id.id,
            'deposit_move_id': self.deposit_move_id.id,
        })
        payment._apply_payment_to_credit_lines()
        payment.write({'state': 'paid'})

        self.write({
            'document_type': 'credit',
            'sale_credit_id': payment.credit_id.id,
            'credit_line_id': payment.credit_line_id.id or self.credit_line_id.id,
            'sale_credit_payment_id': payment.id,
            'move_id': payment.move_id.id,
            'distribution_move_id': payment.distribution_move_id.id,
            'intercompany_move_id': payment.intercompany_move_id.id,
            'deposit_move_id': payment.deposit_move_id.id,
            'state': 'distributed',
        })

        return {
            'success': True,
            'payment_id': payment.id,
            'receipt_id': self.id,
            'move_id': payment.move_id.id,
        }
