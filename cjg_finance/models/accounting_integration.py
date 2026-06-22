# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class SaleCreditPaymentAccounting(models.Model):
    """
    Extensión de sale.credit.payment para integración contable automática
    """
    _inherit = 'sale.credit.payment'
    
    
    # Referencia al cierre de caja
    cash_closing_id = fields.Many2one('cash.box.closing', string='Cierre de Caja', readonly=True, copy=False)
    
    # Referencia al asiento contable generado
    account_move_id = fields.Many2one(
        'account.move',
        string='Asiento Contable',
        help='Asiento contable generado automáticamente al registrar el pago',
        readonly=True,
        copy=False
    )
    

    
    def _prepare_account_move_vals(self):
        """
        Preparar valores para crear el asiento contable
        """
        self.ensure_one()
        
        # Obtener configuración de cuentas desde la compañía
        # Si el contrato no tiene compañía, usar la del usuario actual
        company = self.company_id or self.env.company
        
        # Cuentas configuradas (se configurarán en res.company)
        receivable_account = self.credit_id.partner_id.property_account_receivable_id
        if not receivable_account:
            raise UserError(
                _('El cliente %s no tiene cuenta por cobrar configurada.') % 
                self.credit_id.partner_id.name
            )
        
        # Cuenta de ingreso (desde configuración de compañía o producto)
        income_account = company.credit_income_account_id
        if not income_account:
            raise UserError(
                _('No hay cuenta de ingreso de créditos configurada en la compañía. '
                  'Por favor configure en Financiamiento > Configuración > Ajustes.')
            )
        
        # Crear líneas del asiento
        line_vals = []
        
        # Línea 1: Débito en Caja/Banco (según método de pago)
        cash_account = self._get_cash_account()
        line_vals.append((0, 0, {
            'name': f'Pago {self.credit_id.name} - {self.payment_date}',
            'account_id': cash_account.id,
            'partner_id': self.credit_id.partner_id.id,
            'debit': self.amount,
            'credit': 0.0,
            'date': self.payment_date,
        }))
        
        # Línea 2: Crédito en Cuentas por Cobrar
        line_vals.append((0, 0, {
            'name': f'Pago {self.credit_id.name} - {self.payment_date}',
            'account_id': receivable_account.id,
            'partner_id': self.credit_id.partner_id.id,
            'debit': 0.0,
            'credit': self.amount,
            'date': self.payment_date,
        }))
        
        # Preparar vals del asiento
        move_vals = {
            'move_type': 'entry',
            'date': self.payment_date,
            'ref': f'Pago Crédito {self.credit_id.name}',
            'journal_id': self._get_journal().id,
            'line_ids': line_vals,
            'currency_id': self.currency_id.id,
        }
        
        return move_vals
    
    def _get_cash_account(self):
        """Obtener cuenta de caja según tipo de servicio del crédito"""
        self.ensure_one()
        
        company = self.company_id or self.env.company
        
        # Determinar tipo de servicio del crédito
        service_type = False
        if self.credit_id:
            service_type = self.credit_id.service_type
        
        # Seleccionar cuenta según tipo de servicio
        cash_account = None
        
        if service_type == 'pf':
            cash_account = company.pf_cash_account_id
        elif service_type in ['cm', 'osa', 'jm']:
            cash_account = company.cm_cash_account_id
        elif service_type == 'cre':
            cash_account = company.cre_cash_account_id
        elif service_type == 'sf':
            cash_account = company.sf_cash_account_id
        
        # Fallback a cuenta general de créditos
        if not cash_account:
            cash_account = company.credit_cash_account_id
        
        if not cash_account:
            raise UserError(
                _('No hay cuenta de caja configurada para pagos de crédito tipo %s. '
                  'Por favor configure en Financiamiento > Configuración > Ajustes.') % 
                (service_type or 'general')
            )
        
        return cash_account
    
    def _get_journal(self):
        """Obtener diario contable según tipo de servicio"""
        self.ensure_one()
        
        company = self.company_id or self.env.company
        
        # Determinar tipo de servicio
        service_type = False
        if self.credit_id:
            service_type = self.credit_id.service_type
        
        # Seleccionar diario según tipo de servicio
        journal = None
        
        if service_type == 'pf':
            journal = company.pf_journal_id
        elif service_type in ['cm', 'osa', 'jm']:
            journal = company.cm_journal_id
        elif service_type == 'cre':
            journal = company.cre_journal_id
        elif service_type == 'sf':
            journal = company.sf_journal_id
        
        # Fallback a diario general
        if not journal:
            journal = company.credit_payment_journal_id
        
        # Fallback a primer diario de caja
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'cash'),
                ('company_id', '=', company.id)
            ], limit=1)
            
            if not journal:
                raise UserError(
                    _('No se encontró un diario de tipo Caja para %s. '
                      'Por favor cree uno o configure el diario en los ajustes.') %
                    (service_type or 'pagos')
                )
        
        return journal
    
    def _create_accounting_entries(self):
        """
        Crear asiento contable automáticamente al registrar el pago
        """
        for payment in self:
            if payment.is_migrated:
                continue

            if payment.account_move_id:
                raise UserError(
                    _('Este pago ya tiene un asiento contable asociado.')
                )
            
            # Preparar valores del asiento
            move_vals = payment._prepare_account_move_vals()
            
            # Crear asiento
            move = self.env['account.move'].create(move_vals)
            
            # Registrar asiento
            move.action_post()
            
            # Vincular asiento al pago
            payment.write({'account_move_id': move.id})
    
    def action_post(self):
        """
        Override para crear asiento contable al registrar pago
        """
        res = super(SaleCreditPaymentAccounting, self).action_post()
        
        # Crear asientos contables para pagos registrados
        for payment in self:
            if not payment.account_move_id:
                try:
                    payment._create_accounting_entries()
                except Exception as e:
                    raise UserError(
                        _('Error al crear asiento contable: %s\n\n'
                          'El pago se registró pero no se creó la contabilidad. '
                          'Por favor contacte al administrador.') % str(e)
                    )
        
        return res
    
    def action_cancel(self, reason=None):
        """
        Override para cancelar/revertir asiento contable
        """
        # Revertir asientos contables
        for payment in self:
            if payment.account_move_id and payment.account_move_id.state == 'posted':
                # Crear asiento de reversa
                payment.account_move_id._reverse_moves(
                    default_values_list=[{
                        'ref': f'Reversa: {payment.account_move_id.ref}',
                        'date': fields.Date.context_today(self),
                    }],
                    cancel=True
                )
        
        return super(SaleCreditPaymentAccounting, self).action_cancel(reason=reason)
    
    def unlink(self):
        """
        Override para prevenir borrado si tiene asiento contable
        """
        for payment in self:
            if payment.account_move_id:
                if payment.account_move_id.state == 'posted':
                    raise UserError(
                        _('No puede eliminar un pago con asiento contable registrado. '
                          'Debe primero cancelar el pago.')
                    )
                else:
                    # Borrar asiento en borrador
                    payment.account_move_id.unlink()
        
        return super(SaleCreditPaymentAccounting, self).unlink()


class MaintenanceContractPaymentAccounting(models.Model):
    """
    Extensión de maintenance.contract.payment para integración contable
    """
    _inherit = 'maintenance.contract.payment'
    
    # Referencia al cierre de caja
    cash_closing_id = fields.Many2one('cash.box.closing', string='Cierre de Caja', readonly=True, copy=False)
    
    def _prepare_account_move_vals(self):
        """
        Preparar valores para crear el asiento contable de mantenimiento
        """
        self.ensure_one()
        
        company = self.company_id or self.env.company
        
        # Cuentas del cliente
        receivable_account = self.partner_id.property_account_receivable_id
        if not receivable_account:
            raise UserError(
                _('El cliente %s no tiene cuenta por cobrar configurada.') % 
                self.partner_id.name
            )
        
        # Cuenta de ingreso de mantenimiento
        income_account = company.maintenance_income_account_id
        if not income_account:
            raise UserError(
                _('No hay cuenta de ingreso de mantenimiento configurada. '
                  'Por favor configure en Financiamiento > Configuración > Ajustes.')
            )
        
        # Cuenta de caja
        cash_account = company.maintenance_cash_account_id or company.credit_cash_account_id
        if not cash_account:
            raise UserError(_('No hay cuenta de caja configurada.'))
        
        # Crear líneas del asiento
        line_vals = []
        
        # Débito: Caja/Banco
        line_vals.append((0, 0, {
            'name': f'Pago Mantenimiento {self.contract_id.name}',
            'account_id': cash_account.id,
            'partner_id': self.partner_id.id,
            'debit': self.amount,
            'credit': 0.0,
            'date': self.payment_date,
        }))
        
        # Crédito: Ingreso de Mantenimiento
        line_vals.append((0, 0, {
            'name': f'Pago Mantenimiento {self.contract_id.name}',
            'account_id': income_account.id,
            'partner_id': self.partner_id.id,
            'debit': 0.0,
            'credit': self.amount,
            'date': self.payment_date,
        }))
        
        # Diario
        journal = company.maintenance_payment_journal_id or company.credit_payment_journal_id
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'cash'),
                ('company_id', '=', company.id)
            ], limit=1)
        
        move_vals = {
            'move_type': 'entry',
            'date': self.payment_date,
            'ref': f'Pago Mantenimiento {self.contract_id.name}',
            'journal_id': journal.id,
            'line_ids': line_vals,
            'currency_id': self.currency_id.id,
        }
        
        return move_vals
    
    def _create_accounting_entries(self):
        """Crear asiento contable para pago de mantenimiento"""
        for payment in self:
            if payment.account_move_id:
                continue
            
            move_vals = payment._prepare_account_move_vals()
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            
            payment.write({'account_move_id': move.id})
    
    def action_post(self):
        """Override para crear contabilidad"""
        res = super(MaintenanceContractPaymentAccounting, self).action_post()
        
        for payment in self:
            if not payment.account_move_id:
                try:
                    payment._create_accounting_entries()
                except Exception as e:
                    raise UserError(
                        _('Error al crear asiento contable: %s') % str(e)
                    )
        
        return res
