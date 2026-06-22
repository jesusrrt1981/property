from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_is_zero
from datetime import datetime
import logging
import calendar
_logger = logging.getLogger(__name__)

class PosSession(models.Model):
    _inherit = 'cjg.pos.session'

    @api.model
    def _get_partner_credit_info(self, partner_id):
        all_company_ids = self.env['res.company'].sudo().search([]).ids
        credit_count = self.env['sale.credit'].sudo().with_context(allowed_company_ids=all_company_ids).search_count([
            ('partner_id', '=', partner_id),
            ('state', 'in', ['approved', 'requested', 'active', 'pending', 'verified', 'resent', 'draft'])
        ])
        return {'has_credits': credit_count > 0, 'credit_count': credit_count}

    def _first_unpaid_credit_line(self, credit, CreditLineModel, closed_states):
        return CreditLineModel.search([
            ('credit_id', '=', credit.id),
            ('state', 'not in', closed_states),
            ('amount_residual', '>', 0.0),
        ], limit=1, order='expected_date_payment asc, id asc')

    def _credit_search_result(self, credit, line=False, relation_label=False, relation_partner=False):
        partner = credit.partner_id
        cuota = (line.count or 0) if line else 0
        base_label = f"{credit.name} / Cuota {cuota}" if cuota else credit.name
        credit_name = base_label
        if relation_label and relation_partner:
            credit_name = f"{base_label} / {relation_label}: {relation_partner.name}"
        address_parts = [
            partner.street or '',
            partner.street2 or '',
            partner.city or '',
            partner.state_id.name if partner.state_id else '',
            partner.country_id.name if partner.country_id else '',
        ]
        return {
            'id': f"credit_line:{line.id}" if line else f"credit:{credit.id}",
            'type': 'credit_installment' if line else 'credit_contract',
            'partner_id': partner.id,
            'name': partner.name or '',
            'vat': partner.vat or '',
            'email': partner.email or '',
            'phone': partner.phone or partner.mobile or '',
            'street': partner.street or '',
            'street2': partner.street2 or '',
            'city': partner.city or '',
            'state_name': partner.state_id.name if partner.state_id else '',
            'country_name': partner.country_id.name if partner.country_id else '',
            'address': ', '.join(part for part in address_parts if part),
            'credit_id': credit.id,
            'credit_line_id': line.id if line else False,
            'credit_name': credit_name,
            'relationship_label': relation_label or '',
            'related_partner_name': relation_partner.name if relation_partner else '',
            'related_partner_vat': relation_partner.vat if relation_partner else '',
        }

    @api.model
    def _search_credit_relationships(self, query, CreditLineModel, all_company_ids, allowed_states, closed_states):
        """Paridad Testarossa caja.searchByContrato().

        Testarossa permite buscar una cuenta por titular, representante o beneficiario.
        En Odoo el titular vive en sale.credit.partner_id y las relaciones viven en
        credit.representative / credit.beneficiary cuando cjg_finance_contracts está instalado.
        Este hook es aditivo: si esos modelos no existen, no afecta la caja.
        """
        results = []
        seen_credit_ids = set()
        relation_models = [
            ('credit.representative', _('Representante')),
            ('credit.beneficiary', _('Beneficiario')),
        ]
        for model_name, label in relation_models:
            if model_name not in self.env:
                continue
            Relation = self.env[model_name].sudo().with_context(
                allowed_company_ids=all_company_ids,
                active_test=True,
            )
            components = [
                ('partner_id.name', 'ilike', query),
                ('partner_id.vat', 'ilike', query),
                ('partner_id.ref', 'ilike', query),
                ('partner_id.phone', 'ilike', query),
                ('partner_id.mobile', 'ilike', query),
                ('partner_id.email', 'ilike', query),
                ('credit_id.name', 'ilike', query),
            ]
            relation_domain = [('active', '=', True), ('credit_id.state', 'in', allowed_states)] + ['|'] * (len(components) - 1) + components
            relations = Relation.search(relation_domain, limit=20, order='sequence, id')
            for relation in relations:
                credit = relation.credit_id
                if not credit or credit.id in seen_credit_ids:
                    continue
                line = self._first_unpaid_credit_line(credit, CreditLineModel, closed_states)
                if not line:
                    continue
                seen_credit_ids.add(credit.id)
                results.append(self._credit_search_result(
                    credit,
                    line=line,
                    relation_label=label,
                    relation_partner=relation.partner_id,
                ))
        return results

    @api.model
    def _search_credit_contracts(self, query):
        if not query:
            return []

        import re as _re
        results = []

        normalized = query.replace('-', '').replace(' ', '').strip()
        numeric_part = _re.sub(r'[^0-9]', '', query)

        all_company_ids = self.env['res.company'].sudo().search([]).ids
        CreditModel = self.env['sale.credit'].sudo().with_context(allowed_company_ids=all_company_ids, active_test=False)
        CreditLineModel = self.env['sale.credit.line'].sudo().with_context(allowed_company_ids=all_company_ids, active_test=False)

        allowed_states = ['approved', 'requested', 'active', 'pending', 'verified', 'resent', 'draft', 'legal', 'withdrawing', 'withdrawn']
        closed_states = ['paid', 'cancelled']
        current_search_states = ['approved', 'requested', 'active', 'pending', 'verified', 'resent', 'draft', 'legal', 'withdrawing', 'withdrawn']

        credit_domain_components = [
            ('name', 'ilike', query),
            ('partner_id.name', 'ilike', query),
            ('partner_id.vat', 'ilike', query),
            ('partner_id.ref', 'ilike', query),
        ]
        if normalized and normalized != query:
            credit_domain_components.append(('name', 'ilike', normalized))
        if numeric_part and numeric_part not in (query, normalized):
            credit_domain_components.append(('name', 'ilike', numeric_part))
        n = len(credit_domain_components)
        or_prefix = ['|'] * (n - 1)
        credit_domain = or_prefix + credit_domain_components

        credits = CreditModel.search(credit_domain, limit=20, order='name')
        for credit in credits:
            unpaid_line = self._first_unpaid_credit_line(credit, CreditLineModel, closed_states)
            item = self._credit_search_result(credit, line=unpaid_line) if unpaid_line else self._credit_search_result(credit)
            if credit.state not in current_search_states or not unpaid_line:
                item['credit_id'] = False
                item['credit_line_id'] = False
                item['credit_name'] = _('%s / encontrado por contrato histórico (%s)') % (credit.name, credit.state or _('sin estado'))
                item['load_credit_modal'] = False
            else:
                item['load_credit_modal'] = True
            results.append(item)

        line_domain_components = [
            ('credit_id.name', 'ilike', query),
            ('name', 'ilike', query),
            ('partner_id.name', 'ilike', query),
            ('partner_id.vat', 'ilike', query),
        ]
        if normalized and normalized != query:
            line_domain_components.append(('credit_id.name', 'ilike', normalized))
            line_domain_components.append(('name', 'ilike', normalized))
        if numeric_part and numeric_part not in (query, normalized):
            line_domain_components.append(('credit_id.name', 'ilike', numeric_part))
            line_domain_components.append(('name', 'ilike', numeric_part))

        n2 = len(line_domain_components)
        or_prefix2 = ['|'] * (n2 - 1)
        line_domain = [
            ('state', 'not in', closed_states),
            ('amount_residual', '>', 0.0),
        ] + or_prefix2 + line_domain_components

        lines = CreditLineModel.search(line_domain, limit=20, order='expected_date_payment asc, id asc')
        for line in lines:
            item = self._credit_search_result(line.credit_id, line=line)
            if line.credit_id.state not in current_search_states:
                item['credit_id'] = False
                item['credit_line_id'] = False
                item['credit_name'] = _('%s / encontrado por contrato histórico (%s)') % (line.credit_id.name, line.credit_id.state or _('sin estado'))
                item['load_credit_modal'] = False
            else:
                item['load_credit_modal'] = True
            results.append(item)

        results.extend(self._search_credit_relationships(
            query,
            CreditLineModel,
            all_company_ids,
            allowed_states,
            closed_states,
        ))
        return results


    @api.model
    def get_partner_credit_data(self, partner_id):
        if not partner_id:
            return []
        
        # Buscar créditos activos del partner en TODAS las empresas
        all_company_ids = self.env['res.company'].sudo().search([]).ids
        allowed_states = ['approved', 'requested', 'active', 'pending', 'verified', 'resent', 'draft', 'legal', 'withdrawing']
        credits = self.env['sale.credit'].sudo().with_context(allowed_company_ids=all_company_ids).search([
            ('partner_id', '=', partner_id),
            ('state', 'in', allowed_states),
            ('active', '=', True)
        ], order='name')
        
        result = []
        today = fields.Date.today()
        month_last_day = calendar.monthrange(today.year, today.month)[1]
        cutoff_date = today.replace(day=month_last_day)
        def _serialize_line(line):
            company_curr = line.company_id.currency_id
            line_curr = line.currency_id or line.credit_id.currency_id_money or self.env.company.currency_id
            amt_residual_company = line_curr._convert(
                line.amount_residual, company_curr, line.company_id, today
            )
            return {
                'id': line.id,
                'count': line.count,
                'number': line.count,
                'amount_capital': line.amount_capital,
                'amount_interest': line.amount_interest,
                'amount_fixed': line.amount_fixed,
                'amount_residual': line.amount_residual,
                'amount_residual_company': amt_residual_company,
                'amount_due': line.amount_residual,
                'amount_total': line.amount_residual,
                'amount_paid_total': line.amount_paid_total,
                'expected_date_payment': line.expected_date_payment.isoformat() if line.expected_date_payment else None,
                'date': line.expected_date_payment.isoformat() if line.expected_date_payment else None,
                'state': line.state,
            }

        for credit in credits:
            credit_lines = self.env['sale.credit.line'].sudo().search([
                ('credit_id', '=', credit.id),
                ('active', '=', True),
                ('amount_residual', '>', 0.0),
                ('state', 'not in', ['paid', 'cancelled']),
            ], order='expected_date_payment asc, count asc, id asc')

            due_lines = []
            for line in credit_lines:
                if line.state in ('paid_overdue', 'paid_reload'):
                    due_lines.append(line)
                    continue
                if line.expected_date_payment and line.expected_date_payment <= cutoff_date:
                    due_lines.append(line)

            if not due_lines and credit_lines:
                due_lines = credit_lines[:1]

            due_ids = {l.id for l in due_lines}
            next_line = None
            for line in credit_lines:
                if line.id not in due_ids:
                    next_line = line
                    break
            
            installments = []
            for line in due_lines:
                installments.append(_serialize_line(line))
            
            result.append({
                'id': credit.id,
                'name': credit.name,
                'state': credit.state,
                'amount_total': credit.amount_financed,
                'total_due': sum(l['amount_due'] for l in installments),
                'amount_due': sum(l['amount_due'] for l in installments),
                'currency_id': credit.currency_id_money.id,
                'currency_symbol': credit.currency_id_money.symbol,
                'installments_total_pending': len(credit_lines),
                'installments_due_count': len(due_lines),
                'installments': installments,
                'next_installment': _serialize_line(next_line) if next_line else None,
            })
        return result

    @api.model
    def _process_credit_lines_payment(self, *args, **kwargs):
        # action_confirm(receipt) still calls this hook for backward compatibility.
        # The real allocation path is process_ui_payment(...), so receipt-only calls are no-op.
        if len(args) == 1 and getattr(args[0], '_name', None) == 'cjg.pos.payment.receipt':
            return False
        (payload, session, partner, payment_pool, receipts, receipt_entries, custom_credit_amounts,
         _allocate_payment, _create_receipt, _register_company, credits_to_optimize) = args

        def _safe_rounding(currency):
            rounding = currency.rounding if currency else 0.0
            if not rounding or rounding <= 0.0:
                rounding = 0.01
            return rounding

        # 1. PROCESAR DESGLOSE DE REQUERIMIENTO (TESTAROSSA REQUERIMIENTO BREAKDOWN)
        applied_req = payload.get('applied_requerimiento', [])
        if applied_req:
            _logger.info("=== PROCESANDO DESGLOSE DE REQUERIMIENTO (TESTAROSSA) ===")
            for item in applied_req:
                rtype = item.get('type')
                rid = item.get('id')
                ramount = float(item.get('amount', 0.0))
                
                if float_is_zero(ramount, precision_rounding=0.01):
                    continue
                
                if rtype == 'fin':
                    # Es una cuota de crédito
                    credit_line = self.env['sale.credit.line'].browse(rid)
                    if not credit_line.exists(): continue
                    
                    currency = credit_line.credit_id.currency_id_money or session.currency_id
                    allocations, remaining = _allocate_payment(ramount, currency)
                    
                    if allocations:
                        company_id = _register_company(credit_line.credit_id.company_id.id or self.env.company.id)
                        for alloc in allocations:
                            receipt = _create_receipt({
                                'session_id': session.id,
                                'partner_id': partner.id,
                                'document_type': 'credit',
                                'sale_credit_id': credit_line.credit_id.id,
                                'credit_line_id': credit_line.id,
                                'amount_total': credit_line.amount_residual,
                                'amount_paid': alloc['amount'],
                                'amount_currency': alloc.get('original_amount', 0.0),
                                'payment_method_id': alloc['payment_method_id'],
                                'instrument_id': alloc['instrument_id'],
                                'pos_reference': alloc['pos_reference'],
                                'company_id': company_id,
                            })
                            receipts |= receipt
                            receipt_entries.append({
                                'id': receipt.id, 'name': receipt.name, 'document_type': 'credit',
                                'amount_paid': receipt.amount_paid, 'credit_line_id': credit_line.id
                            })
                            credit_line.write({'amount_paid_total': credit_line.amount_paid_total + alloc.get('original_amount', alloc['amount'])})
                            if credit_line.amount_residual < 0.01: credit_line.state = 'paid'

                elif rtype == 'mto':
                    # Es un contrato de mantenimiento
                    mto_contract = self.env['maintenance.contract'].browse(rid)
                    if not mto_contract.exists(): continue
                    
                    currency = mto_contract.currency_id or session.currency_id
                    allocations, remaining = _allocate_payment(ramount, currency)
                    
                    if allocations:
                        company_id = _register_company(mto_contract.company_id.id or self.env.company.id)
                        for alloc in allocations:
                            # Nota: MAINTENANCE_CONTRACT_ID debe existir en cjg.pos.payment.receipt
                            receipt_vals = {
                                'session_id': session.id,
                                'partner_id': partner.id,
                                'document_type': 'maintenance',
                                'maintenance_contract_id': mto_contract.id,
                                'amount_total': mto_contract.balance,
                                'amount_paid': alloc['amount'],
                                'amount_currency': alloc.get('original_amount', 0.0),
                                'payment_method_id': alloc['payment_method_id'],
                                'instrument_id': alloc['instrument_id'],
                                'pos_reference': alloc['pos_reference'],
                                'company_id': company_id,
                            }
                            receipt = _create_receipt(receipt_vals)
                            receipts |= receipt
                            receipt_entries.append({
                                'id': receipt.id, 'name': receipt.name, 'document_type': 'maintenance',
                                'amount_paid': receipt.amount_paid, 'contract_name': mto_contract.name
                            })
            
            # Si procesamos breakdown, salimos para no duplicar con la lógica Legacy posterior
            return receipts

        # 2. LÓGICA LEGACY (Solo si no hay breakdown detallado)
        credit_lines = self.env['sale.credit.line'].browse(payload.get('credit_line_ids', [])) if payload.get('credit_line_ids') else self.env['sale.credit.line'].browse()

        for credit_line in credit_lines:
            if not credit_line.exists():
                continue
            base_amount = credit_line.amount_residual or 0.0
            currency = getattr(credit_line, 'currency_id', False) or getattr(credit_line.credit_id, 'currency_id_money', False) or session.currency_id
            if float_is_zero(base_amount, precision_rounding=_safe_rounding(currency)):
                continue
            
            # Manejar monto personalizado
            custom_val = custom_credit_amounts.get(credit_line.id) or custom_credit_amounts.get(str(credit_line.id))
            if custom_val is not None:
                pos_curr = session.currency_id or self.env.company.currency_id
                target_amount = pos_curr._convert(
                    float(custom_val), currency, credit_line.company_id, fields.Date.today()
                )
                target_amount = min(target_amount, base_amount)
            else:
                target_amount = base_amount

            if float_is_zero(target_amount, precision_rounding=_safe_rounding(currency)):
                continue
                
            allocations, remaining = _allocate_payment(target_amount, currency)
            if not allocations or not float_is_zero(remaining, precision_rounding=_safe_rounding(currency)):
                precision_lenient = 0.10 if currency != session.currency_id else _safe_rounding(currency)
                if not float_is_zero(remaining, precision_rounding=precision_lenient):
                    raise UserError(_("Los pagos disponibles no alcanzan para la cuota %s. (Faltan %s %s)") % (credit_line.display_name, remaining, currency.name))
            
            company_id = (
                credit_line.company_id.id
                if getattr(credit_line, 'company_id', False)
                else (credit_line.credit_id.company_id.id if credit_line.credit_id and credit_line.credit_id.company_id else self.env.company.id)
            )
            company_id = _register_company(company_id)
            for alloc in allocations:
                receipt_vals = {
                    'session_id': session.id,
                    'partner_id': partner.id,
                    'document_type': 'credit',
                    'sale_credit_id': credit_line.credit_id.id,
                    'credit_line_id': credit_line.id, # Note: this will need extension in document model too
                    'amount_total': base_amount,
                    'amount_paid': alloc['amount'],
                    'amount_currency': alloc.get('original_amount', 0.0),
                    'foreign_currency_id': currency.id if currency.id != session.currency_id.id else False,
                    'payment_method_id': alloc['payment_method_id'],
                    'instrument_id': alloc['instrument_id'],
                    'point_id': alloc['point_id'],
                    'deposit_journal_id': alloc['deposit_journal_id'],
                    'pos_reference_type': alloc['pos_reference_type'],
                    'pos_reference': alloc['pos_reference'],
                    'company_id': company_id,
                }
                receipt = _create_receipt(receipt_vals)
                receipts |= receipt
                receipt_entries.append({
                    'id': receipt.id,
                    'name': receipt.name,
                    'document_type': 'credit',
                    'amount_paid': receipt.amount_paid,
                    'credit_line_id': credit_line.id,
                })
                
                new_paid_total = credit_line.amount_paid_total + alloc.get('original_amount', alloc['amount'])
                new_residual = max(0.0, credit_line.amount_residual - alloc.get('original_amount', alloc['amount']))
                update_vals = {
                    'amount_paid_total': new_paid_total,
                    'amount_residual': new_residual,
                }
                if float_is_zero(new_residual, precision_rounding=_safe_rounding(currency)):
                    update_vals['state'] = 'paid'
                credit_line.write(update_vals)
                credit_line.pos_payment_ids = [(4, receipt.id)]
            credits_to_optimize |= credit_line.credit_id
        return receipts
    @api.model
    def get_partner_requerimiento_data(self, partner_id, credit_id=None, maintenance_contract_id=None):
        """
        Consolidates finance and maintenance contracts into a single 'Requerimiento' structure.
        Returns one row per CONTRACT, but includes the list of installments inside for internal allocation.
        """
        if not partner_id:
            return []
        
        all_company_ids = self.env['res.company'].sudo().search([]).ids
        today = fields.Date.today()
        _logger.info("CJG_REQ: Fetching Contract-based Requerimiento (with lines) for partner_id: %s (Type: %s)", partner_id, type(partner_id))
        
        # 1. Fetch Finance Credits
        excluded_credit_states = ['refuse', 'cancelled', 'closed', 'forgiven']
        credit_domain = [
            ('partner_id', '=', partner_id),
            ('state', 'not in', excluded_credit_states),
        ]
        if credit_id:
            credit_domain.append(('id', '=', credit_id))
        credits = self.env['sale.credit'].sudo().with_context(allowed_company_ids=all_company_ids, active_test=False).search(
            credit_domain,
            order='name',
        )
        
        # 2. Fetch Maintenance Contracts. Para mantenimiento, la búsqueda debe servir
        # también para contratos financieros saldados/históricos; si el cajero buscó
        # un contrato específico se filtra a ese mantenimiento, si no, se muestran
        # los mantenimientos existentes del cliente.
        maintenance_domain = [('partner_id', '=', partner_id)]
        if maintenance_contract_id:
            maintenance_domain.append(('id', '=', maintenance_contract_id))
        maintenance_contracts = self.env['maintenance.contract'].sudo().with_context(
            allowed_company_ids=all_company_ids,
            active_test=False,
        ).search(maintenance_domain, order='name')
        
        result = []
        _logger.info("CJG_REQ: Found %s credits and %s maintenance contracts", len(credits), len(maintenance_contracts))
        if credits:
            _logger.info("CJG_REQ: Credits IDs: %s", credits.ids)
        if maintenance_contracts:
            _logger.info("CJG_REQ: Maintenance IDs: %s", maintenance_contracts.ids)

        def _round_amount(value):
            return round(float(value or 0.0), 2)

        # Process Credits
        for credit in credits:
            lines = self.env['sale.credit.line'].sudo().with_context(active_test=False).search([
                ('credit_id', '=', credit.id),
                ('state', 'not in', ['paid', 'cancelled']),
                ('amount_residual', '>', 0.0)
            ], order='expected_date_payment asc')
            
            # Buckets
            buckets = {'1-30': 0.0, '31-60': 0.0, '61-90': 0.0, 'plus_90': 0.0, 'vencido': 0.0, 'no_vencido': 0.0}
            line_data = []
            for line in lines:
                diff = (today - line.expected_date_payment).days if line.expected_date_payment else 0
                amt = float(line.amount_residual or 0.0)
                if diff > 0:
                    buckets['vencido'] += amt
                    if diff <= 30: buckets['1-30'] += amt
                    elif diff <= 60: buckets['31-60'] += amt
                    elif diff <= 90: buckets['61-90'] += amt
                    else: buckets['plus_90'] += amt
                else:
                    buckets['no_vencido'] += amt
                
                line_data.append({
                    'id': line.id,
                    'name': line.count,
                    'amount_fixed': _round_amount(line.amount_fixed or line.amount_residual),
                    'amount_residual': _round_amount(line.amount_residual),
                    'expected_date_payment': line.expected_date_payment.isoformat() if line.expected_date_payment else ''
                })

            total_debt = _round_amount(sum(lines.mapped('amount_residual')))

            # ULTIMO PAGO
            last_payment = self.env['sale.credit.payment'].sudo().search([
                ('credit_id', '=', credit.id),
                ('state', '=', 'posted')
            ], order='payment_date desc', limit=1)
            
            # PAGOS MES
            start_date = today.replace(day=1)
            month_payments = self.env['sale.credit.payment'].sudo().search([
                ('credit_id', '=', credit.id),
                ('state', '=', 'posted'),
                ('payment_date', '>=', start_date),
                ('payment_date', '<=', today)
            ])

            result.append({
                'cat': 'FIN',
                'id': credit.id,
                'name': credit.name,
                'state': credit.state,
                'state_label': dict(credit._fields['state'].selection).get(credit.state, credit.state),
                'product': credit.product_id.name if credit.product_id else '',
                # SPRINT COBROS-CRITICOS 2026-06-20 Fix #3i: helper unificado
                # en JSON de recibo POS.
                'oficial': (
                    credit._get_collection_officer().name
                    if hasattr(credit, '_get_collection_officer')
                    and credit._get_collection_officer()
                    else (credit.oficial_id.name if credit.oficial_id else '')
                ),
                'motorista': credit.motorista_id.name if credit.motorista_id else '',
                'date_contract': credit.date_contract.strftime('%m/%d/%Y') if credit.date_contract else '',
                'currency': credit.currency_id_money.name or 'RD$',
                'amount_per_rate': _round_amount(credit.amount_per_rate),
                'last_payment_date': last_payment.payment_date.strftime('%m/%d/%Y') if last_payment else '',
                'last_payment_amount': _round_amount(last_payment.amount_paid if last_payment else 0.0),
                'month_payments_count': len(month_payments),
                'month_payments_amount': _round_amount(sum(month_payments.mapped('amount_paid'))),
                'req_activo_amount': 0.0,
                'initial_payment': _round_amount(credit.initial_payment_total),
                'aging': {key: _round_amount(val) for key, val in buckets.items()},
                'total_debt': total_debt,
                'installments': line_data, # Detalle interno
                'type': 'fin'
            })

        def _maintenance_pending_amount(mline):
            """Return the amount still payable for a maintenance draft line.

            Migrated Testarossa data and POS-generated maintenance lines do not all
            use the same convention: some draft lines store the payable amount in
            amount_paid/amount, while POS-generated draft lines store it in
            amount_total with amount_paid = 0. Caja must treat draft lines as
            payable, not as already paid.
            """
            total = float(mline.amount_total or 0.0)
            paid = float(mline.amount_paid or 0.0)
            if total > 0.0 and paid < total - 0.01:
                return total - paid
            if mline.state == 'draft':
                return float(mline.amount or 0.0) or paid or total or float(mline.contract_id.maintenance_fee or 0.0)
            return max(total - paid, 0.0)

        # Process Maintenance
        for mto in maintenance_contracts:
            exchange_company = mto._get_exchange_company() if hasattr(mto, '_get_exchange_company') else (mto.company_id or self.env.company)
            pos_currency = exchange_company.currency_id or self.env.company.currency_id
            exchange_info = mto._get_pos_exchange_info(target_currency=pos_currency, date=today) if hasattr(mto, '_get_pos_exchange_info') else {
                'rate': 1.0,
                'source': 'same',
                'is_manual': False,
            }
            exchange_rate = float(exchange_info.get('rate') or 1.0)
            exchange_source = exchange_info.get('source') or 'same'
            exchange_label = ''
            if mto.currency_id and pos_currency and mto.currency_id != pos_currency:
                exchange_label = _('Tasa fija: %.2f') % exchange_rate if exchange_info.get('is_manual') else _('Tasa día: %.2f') % exchange_rate

            def _convert_mto_amount(amount):
                if hasattr(mto, '_convert_maintenance_amount_for_pos'):
                    return _round_amount(mto._convert_maintenance_amount_for_pos(amount, target_currency=pos_currency, date=today))
                return _round_amount(amount)

            def _to_original_mto_amount(amount):
                amount = float(amount or 0.0)
                if not mto.currency_id or not pos_currency or mto.currency_id == pos_currency:
                    return _round_amount(amount)
                if exchange_rate:
                    return _round_amount(amount / exchange_rate)
                return _round_amount(amount)

            periods = self.env['maintenance.period'].sudo().search([
                ('contract_id', '=', mto.id),
                ('concept_code', '=', '106'),
                ('state', '=', 'pending'),
            ], order='due_date asc, sequence asc')
            mlines = self.env['maintenance.contract.payment'].sudo().search([
                ('contract_id', '=', mto.id),
                ('state', '=', 'draft')
            ], order='payment_date asc') if not periods else self.env['maintenance.contract.payment']
            
            buckets = {'1-30': 0.0, '31-60': 0.0, '61-90': 0.0, 'plus_90': 0.0, 'vencido': 0.0, 'no_vencido': 0.0}
            line_data = []
            maintenance_total = 0.0
            for period in periods:
                original_amt = period.net_collectible()
                if original_amt <= 0.0:
                    continue
                amt = _convert_mto_amount(original_amt)
                maintenance_total += amt
                diff = (today - period.due_date).days if period.due_date else 0
                buckets['vencido' if diff > 0 else 'no_vencido'] += amt
                line_data.append({
                    'id': period.id,
                    'name': _('Annual maintenance %(sequence)s - %(date)s') % {
                        'sequence': period.sequence, 'date': period.due_date,
                    },
                    'sequence': period.sequence,
                    'due_date': period.due_date.isoformat() if period.due_date else '',
                    'amount_residual': _round_amount(amt),
                    'amount_original_residual': _round_amount(original_amt),
                    'source_model': 'maintenance.period',
                    'currency': mto.currency_id.name if mto.currency_id else '',
                    'target_currency': pos_currency.name if pos_currency else '',
                    'exchange_rate': exchange_rate,
                    'exchange_source': exchange_source,
                    'exchange_label': exchange_label,
                })
            for mline in mlines:
                diff = (today - mline.payment_date).days if mline.payment_date else 0
                original_amt = _maintenance_pending_amount(mline)
                amt = _convert_mto_amount(original_amt)
                maintenance_total += amt
                if diff > 0:
                    buckets['vencido'] += amt
                    if diff <= 30: buckets['1-30'] += amt
                    elif diff <= 60: buckets['31-60'] += amt
                    elif diff <= 90: buckets['61-90'] += amt
                    else: buckets['plus_90'] += amt
                else:
                    buckets['no_vencido'] += amt
                
                line_data.append({
                    'id': mline.id,
                    'name': mline.name or 'Cuota/Gasto',
                    'amount_residual': _round_amount(amt),
                    'amount_original_residual': _round_amount(original_amt),
                    'currency': mto.currency_id.name if mto.currency_id else '',
                    'target_currency': pos_currency.name if pos_currency else '',
                    'exchange_rate': exchange_rate,
                    'exchange_source': exchange_source,
                    'exchange_label': exchange_label,
                })

            total_debt = _round_amount(maintenance_total or _convert_mto_amount(mto.balance))
            if not line_data and total_debt > 0.0:
                line_data.append({
                    'id': mto.id,
                    'name': mto.name or 'Mantenimiento',
                    'amount_residual': total_debt,
                    'amount_original_residual': _to_original_mto_amount(total_debt),
                    'source_model': 'maintenance.contract',
                    'currency': mto.currency_id.name if mto.currency_id else '',
                    'target_currency': pos_currency.name if pos_currency else '',
                    'exchange_rate': exchange_rate,
                    'exchange_source': exchange_source,
                    'exchange_label': exchange_label,
                })

            last_payment = self.env['maintenance.contract.payment'].sudo().search([
                ('contract_id', '=', mto.id),
                ('state', '=', 'posted')
            ], order='payment_date desc', limit=1)

            result.append({
                'cat': 'MTO',
                'id': mto.id,
                'name': mto.name,
                'state': mto.state,
                'state_label': dict(mto._fields['state'].selection).get(mto.state, mto.state),
                'product': mto.sale_credit_id.product_id.name if mto.sale_credit_id and mto.sale_credit_id.product_id else 'Mantenimiento',
                # SPRINT COBROS-CRITICOS 2026-06-20 Fix #3i: helper unificado
                # en JSON de mantenimiento.
                'oficial': (
                    mto.sale_credit_id._get_collection_officer().name
                    if mto.sale_credit_id
                    and hasattr(mto.sale_credit_id, '_get_collection_officer')
                    and mto.sale_credit_id._get_collection_officer()
                    else (
                        mto.sale_credit_id.oficial_id.name
                        if mto.sale_credit_id and mto.sale_credit_id.oficial_id
                        else ''
                    )
                ),
                'motorista': mto.sale_credit_id.motorista_id.name if mto.sale_credit_id and mto.sale_credit_id.motorista_id else '',
                'date_contract': mto.date_start.strftime('%m/%d/%Y') if mto.date_start else '',
                'currency': mto.currency_id.name or 'RD$',
                'currency_id': mto.currency_id.id if mto.currency_id else False,
                'display_currency': pos_currency.name if pos_currency else (mto.currency_id.name or 'RD$'),
                'exchange_rate': exchange_rate,
                'exchange_source': exchange_source,
                'exchange_label': exchange_label,
                'uses_manual_exchange_rate': bool(exchange_info.get('is_manual')),
                'amount_per_rate_original': _round_amount(mto.maintenance_fee or _to_original_mto_amount(total_debt)),
                'amount_per_rate': _convert_mto_amount(mto.maintenance_fee or _to_original_mto_amount(total_debt)),
                'last_payment_date': last_payment.payment_date.strftime('%m/%d/%Y') if last_payment else '',
                'last_payment_amount': _round_amount(last_payment.amount_paid if last_payment else 0.0),
                'req_activo_amount': 0.0,
                'initial_payment': 0.0,
                'aging': {key: _round_amount(val) for key, val in buckets.items()},
                'total_debt': total_debt,
                'installments': line_data,
                'type': 'mto'
            })
        return result

    @api.model
    def get_requerimiento_metadata(self):
        """
        Fetches metadata for Requerimiento modal: oficiais and motoristas.
        """
        # Fetch motoristas (res.partner where is_motorista = True)
        motoristas = self.env['res.partner'].sudo().search([
            ('is_motorista', '=', True),
            ('active', '=', True)
        ], order='name')
        
        # Fetch oficiais (res.users who are associated as oficial_id in sale.credit)
        # We return the partner_id because pos.payment.receipt uses res.partner for user_id
        oficiais = self.env['res.users'].sudo().search([
            ('active', '=', True)
        ], order='name')
        
        company_currency = self.env.company.currency_id
        usd_currency = self.env['res.currency'].sudo().search([('name', '=', 'USD')], limit=1)
        usd_rate = 1.0
        if usd_currency and company_currency and usd_currency != company_currency:
            usd_rate = usd_currency._convert(1.0, company_currency, self.env.company, fields.Date.context_today(self))

        return {
            'motoristas': [{'id': m.id, 'name': m.name} for m in motoristas],
            'oficiales': [{'id': o.partner_id.id, 'name': o.name} for o in oficiais],
            'oficiais': [{'id': o.partner_id.id, 'name': o.name} for o in oficiais],
            'usd_rate': round(float(usd_rate or 1.0), 2),
            'itbis_rate': 18.0,
        }

    @api.model
    def create_requerimiento_receipts(self, payload):
        """
        Creates draft receipts based on the Requerimiento breakdown from the POS.
        """
        _logger.info("CJG_REQ: Creating Requerimiento Receipts with payload: %s", payload)
        
        partner_id = payload.get('partner_id')
        session_id = payload.get('session_id')
        breakdown = payload.get('breakdown', [])
        oficial_id = payload.get('oficial_id')
        motorista_id = payload.get('motorista_id')
        requirement_date = payload.get('requirement_date')
        extra_notes = (payload.get('notes') or '').strip()
        discount_amount = float(payload.get('discount_amount') or 0.0)
        
        if not partner_id or not session_id or not breakdown:
            return {'error': 'Incomplete data to create receipts'}
            
        session = self.browse(session_id)
        partner = self.env['res.partner'].browse(partner_id)
        receipt_date = fields.Datetime.now()
        if requirement_date:
            try:
                receipt_date = fields.Datetime.to_datetime(f"{requirement_date} 00:00:00")
            except Exception:
                receipt_date = fields.Datetime.now()

        receipt_ids = []
        for item in breakdown:
            rtype = item.get('type')
            rid = item.get('id')
            ramount = float(item.get('amount', 0.0))
            
            if float_is_zero(ramount, precision_rounding=0.01):
                continue
                
            company_id = session.cashbox_id.company_id.id if session.cashbox_id and session.cashbox_id.company_id else self.env.company.id
            if rtype == 'fin':
                line = self.env['sale.credit.line'].sudo().browse(rid)
                if line.exists() and line.company_id:
                    company_id = line.company_id.id
            elif rtype == 'mto':
                if item.get('source_model') == 'maintenance.contract':
                    mto_contract = self.env['maintenance.contract'].sudo().browse(rid)
                    original_amount = float(item.get('original_amount') or 0.0)
                    if not original_amount:
                        rate = float(item.get('exchange_rate') or 0.0)
                        original_amount = round(ramount / rate, 2) if rate else ramount
                    mline = self.env['maintenance.contract.payment'].sudo().create({
                        'contract_id': mto_contract.id,
                        'partner_id': mto_contract.partner_id.id or partner.id,
                        'currency_id': mto_contract.currency_id.id or mto_contract.company_id.currency_id.id or self.env.company.currency_id.id,
                        'session_id': session.id,
                        'document_type': 'maintenance',
                        'amount_total': original_amount,
                        'amount_paid': 0.0,
                        'date': receipt_date,
                        'state': 'draft',
                        'notes': item.get('concept') or _('Requerimiento POS %s') % mto_contract.name,
                    }) if mto_contract.exists() else self.env['maintenance.contract.payment'].browse()
                else:
                    mline = self.env['maintenance.contract.payment'].sudo().browse(rid)
                if mline.exists() and mline.company_id:
                    company_id = mline.company_id.id

            # SELECCIÓN DE DIARIO DE COBRO (Testarossa: Caja General de la Empresa)
            clearing_journal = session.cashbox_id.sudo()._get_company_clearing_journal(company_id) if session.cashbox_id else False
            if not clearing_journal:
                # Fallback 1: Buscar diario misceláneo POSGEN
                clearing_journal = session.cashbox_id.sudo()._get_or_create_clearing_journal(company_id) if session.cashbox_id else False
            
            if not clearing_journal:
                # Fallback 2: Buscar diario de efectivo o banco en la compañía destino
                clearing_journal = self.env['account.journal'].sudo().search([
                    ('company_id', '=', company_id),
                    ('type', 'in', ['cash', 'bank'])
                ], limit=1)
                
            if not clearing_journal:
                # Fallback 3: Último recurso, buscar cualquier diario en la compañía
                clearing_journal = self.env['account.journal'].sudo().search([
                    ('company_id', '=', company_id)
                ], limit=1)

            _logger.info("CJG_REQ_DEBUG: Creating receipt for rtype: %s, rid: %s, company_id: %s, journal_id: %s", rtype, rid, company_id, clearing_journal.id if clearing_journal else 'NULL')
            
            receipt_vals = {
                'session_id': session.id,
                'partner_id': partner.id,
                'company_id': company_id,
                'payment_method_id': clearing_journal.id if clearing_journal else False,
                'date': receipt_date,
                'amount_total': ramount,
                'amount_paid': 0.0, # Not paid yet
                'state': 'draft',
                'user_id': oficial_id or False,
                'collector_id': motorista_id or False,
                'notes': f"Requerimiento creado desde POS - {item.get('name', '')}",
            }
            if item.get('original_amount'):
                receipt_vals['amount_currency'] = float(item.get('original_amount') or 0.0)
            if item.get('currency_id'):
                receipt_vals['foreign_currency_id'] = item.get('currency_id')
            
            if rtype == 'fin':
                # El frontend envía el ID de la CUOTA (sale.credit.line) en 'rid'
                receipt_vals.update({
                    'document_type': 'credit',
                    'sale_credit_id': line.credit_id.id,
                    'credit_line_id': line.id,
                    'notes': f"Requerimiento POS - {line.credit_id.name} Cuota {line.count}",
                })
            elif rtype == 'mto':
                # El frontend envía el ID de la línea (maintenance.contract.payment) en 'rid'
                receipt_vals.update({
                    'document_type': 'maintenance',
                    'maintenance_contract_id': mline.contract_id.id,
                    'notes': f"Requerimiento POS - Mantenimiento {mline.contract_id.name} ({mline.name or 'Pago'})",
                })

            note_parts = [receipt_vals.get('notes')]
            if item.get('exchange_rate'):
                note_parts.append(f"Tasa mantenimiento: {round(float(item.get('exchange_rate')), 2):.2f} ({item.get('exchange_source') or 'día'})")
            if item.get('discount_amount'):
                note_parts.append(f"Descuento aplicado: {round(float(item.get('discount_amount')), 2):.2f}")
            elif discount_amount:
                note_parts.append(f"Descuento total modal: {round(discount_amount, 2):.2f}")
            if extra_notes:
                note_parts.append(extra_notes)
            receipt_vals['notes'] = " | ".join([part for part in note_parts if part])
                
            receipt = self.env['cjg.pos.payment.receipt'].sudo().create(receipt_vals)
            receipt_ids.append(receipt.id)
            
        return {'status': 'ok', 'receipt_ids': receipt_ids}
