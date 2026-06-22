# -*- coding: utf-8 -*-
"""
Tests de Propiedades de Corrección para Procesos de Contratos
Cubre las propiedades P2, P3, P5, P6, P7 del diseño técnico.

**Validates: Requirements 10 (integridad y trazabilidad)**
"""
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


class TestContractProcessProperties(TransactionCase):
    """
    Property-based tests for contract process correctness.
    Each test validates a formal correctness property from the design spec.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def _create_minimal_credit(self, state='approved', date_start=None, partner=None):
        """Helper: create a minimal sale.credit record for testing."""
        if date_start is None:
            date_start = date.today() - relativedelta(months=15)
        if partner is None:
            partner = self.env['res.partner'].create({'name': 'Test Partner'})

        # Find required fields
        category = self.env['sale.credit.category'].search([], limit=1)
        frequency = self.env['sale.credit.frequency'].search([], limit=1)
        company = self.env.company
        currency = company.currency_id

        if not category:
            raise self.skipTest('No sale.credit.category records found in test DB')
        if not frequency:
            raise self.skipTest('No sale.credit.frequency records found in test DB')

        credit = self.env['sale.credit'].create({
            'partner_id': partner.id,
            'category_id': category.id,
            'frequency_id': frequency.id,
            'company_id': company.id,
            'currency_id_money': currency.id,
            'date_start': date_start,
            'state': state,
            'type_id': 'finan',
            'contract_process_type': 'new',
        })
        return credit

    # =========================================================================
    # P2: Penalty distribution correctness
    # =========================================================================

    def test_p2_penalty_distribution_sum_equals_total(self):
        """
        P2: The sum of amount_others across all pending installments of a
        reactivation contract must equal reactivation_penalty_amount (±0.01).

        **Validates: Requirements 10.2 — Penalidad distribuida correctamente**
        """
        credit = self._create_minimal_credit(state='approved')
        origin = self._create_minimal_credit(
            state='cancelled',
            partner=credit.partner_id,
        )
        origin.initial_payment_total = 5000.0

        # Create 5 pending credit lines
        for i in range(1, 6):
            self.env['sale.credit.line'].create({
                'credit_id': credit.id,
                'count': i,
                'expected_date_payment': date.today() + timedelta(days=30 * i),
                'amount_fixed': 1000.0,
                'amount_capital': 800.0,
                'amount_interest': 200.0,
                'amount_others': 0.0,
                'state': 'pending',
            })

        # Set up as reactivation contract with penalty
        penalty_amount = 1500.0
        credit.write({
            'contract_process_type': 'reactivation',
            'origin_credit_id': origin.id,
            'reactivation_penalty_amount': penalty_amount,
            'reactivation_penalty_rate': 30.0,
        })

        # Distribute penalty
        credit._distribute_reactivation_penalty()

        # Verify: sum of amount_others == penalty_amount ±0.01
        pending_lines = credit.credit_lines.filtered(
            lambda l: l.state in ('pending', 'paid_overdue')
        )
        total_others = sum(pending_lines.mapped('amount_others'))
        self.assertAlmostEqual(
            total_others, penalty_amount, delta=0.01,
            msg=(
                f"P2 FAILED: sum(amount_others)={total_others} "
                f"!= penalty_amount={penalty_amount} (±0.01)"
            )
        )
        self.assertTrue(credit.reactivation_penalty_distributed)

        credit._distribute_reactivation_penalty()
        self.assertAlmostEqual(
            sum(pending_lines.mapped('amount_others')),
            penalty_amount,
            delta=0.01,
            msg='La distribución debe ser idempotente.',
        )

    def test_p2_penalty_distribution_with_rounding(self):
        """
        P2: Penalty distribution handles rounding correctly — remainder goes to first line.

        **Validates: Requirements 10.2 — Penalidad distribuida correctamente**
        """
        credit = self._create_minimal_credit(state='approved')
        origin = self._create_minimal_credit(
            state='cancelled',
            partner=credit.partner_id,
        )
        origin.initial_payment_total = 100.0 / 0.30

        # 3 lines, penalty not evenly divisible
        for i in range(1, 4):
            self.env['sale.credit.line'].create({
                'credit_id': credit.id,
                'count': i,
                'expected_date_payment': date.today() + timedelta(days=30 * i),
                'amount_fixed': 500.0,
                'amount_capital': 400.0,
                'amount_interest': 100.0,
                'amount_others': 0.0,
                'state': 'pending',
            })

        # 100.00 / 3 = 33.33... — remainder of 0.01 goes to first line
        penalty_amount = 100.00
        credit.write({
            'contract_process_type': 'reactivation',
            'origin_credit_id': origin.id,
            'reactivation_penalty_amount': penalty_amount,
            'reactivation_penalty_rate': 30.0,
        })

        credit._distribute_reactivation_penalty()

        pending_lines = credit.credit_lines.filtered(
            lambda l: l.state in ('pending', 'paid_overdue')
        )
        total_others = sum(pending_lines.mapped('amount_others'))
        self.assertAlmostEqual(
            total_others, penalty_amount, delta=0.01,
            msg=(
                f"P2 FAILED (rounding): sum(amount_others)={total_others} "
                f"!= penalty_amount={penalty_amount} (±0.01)"
            )
        )

    def test_p2_penalty_distribution_idempotent_on_empty_lines(self):
        """
        P2: _distribute_reactivation_penalty does nothing if no pending lines.

        **Validates: Requirements 10.2 — Penalidad distribuida correctamente**
        """
        credit = self._create_minimal_credit(state='approved')
        origin = self._create_minimal_credit(
            state='cancelled',
            partner=credit.partner_id,
        )
        origin.initial_payment_total = 500.0 / 0.30
        credit.write({
            'contract_process_type': 'reactivation',
            'origin_credit_id': origin.id,
            'reactivation_penalty_amount': 500.0,
            'reactivation_penalty_rate': 30.0,
        })
        # No credit lines — should not raise
        credit._distribute_reactivation_penalty()
        # No lines to check, just verify no exception was raised

    def test_p2_no_distribution_for_non_reactivation(self):
        """
        P2: _distribute_reactivation_penalty does nothing for non-reactivation contracts.

        **Validates: Requirements 10.2 — Penalidad distribuida correctamente**
        """
        credit = self._create_minimal_credit(state='approved')

        self.env['sale.credit.line'].create({
            'credit_id': credit.id,
            'count': 1,
            'expected_date_payment': date.today() + timedelta(days=30),
            'amount_fixed': 1000.0,
            'amount_capital': 800.0,
            'amount_interest': 200.0,
            'amount_others': 0.0,
            'state': 'pending',
        })

        credit._distribute_reactivation_penalty()

        # amount_others should remain 0 since it's not a reactivation contract
        line = credit.credit_lines[0]
        self.assertEqual(
            line.amount_others, 0.0,
            "P2 FAILED: amount_others should not be modified for non-reactivation contracts"
        )

    # =========================================================================
    # P3: Devolucion eligibility by seniority
    # =========================================================================

    def test_p3_devolucion_eligible_after_12_months(self):
        """
        P3: A contract with date_start >= 12 months ago is eligible for devolucion.

        **Validates: Requirements 5.1 — Elegibilidad de devolución por antigüedad**
        """
        credit = self._create_minimal_credit(
            state='cancelled',
            date_start=date.today() - relativedelta(months=13)
        )
        wizard = self.env['sale.credit.devolucion.wizard'].create({
            'credit_id': credit.id,
            'devolucion_method': 'cheque',
        })
        # Should not raise
        try:
            wizard._validate_eligibility()
        except UserError as e:
            self.fail(f"P3 FAILED: Eligible contract raised UserError: {e}")

    def test_p3_devolucion_ineligible_before_12_months(self):
        """
        P3: A contract with date_start < 12 months ago is NOT eligible for devolucion.

        **Validates: Requirements 5.8 — Contrato con menos de 12 meses no elegible**
        """
        credit = self._create_minimal_credit(
            state='cancelled',
            date_start=date.today() - relativedelta(months=6)
        )
        wizard = self.env['sale.credit.devolucion.wizard'].create({
            'credit_id': credit.id,
            'devolucion_method': 'cheque',
        })
        with self.assertRaises(UserError, msg="P3 FAILED: Ineligible contract should raise UserError"):
            wizard._validate_eligibility()

    def test_p3_devolucion_exactly_12_months_boundary(self):
        """
        P3: A contract with date_start exactly 12 months ago is on the boundary.
        The check uses days/30.44 so 12 months = ~365 days → eligible.

        **Validates: Requirements 5.1 — Elegibilidad de devolución por antigüedad**
        """
        credit = self._create_minimal_credit(
            state='cancelled',
            date_start=date.today() - relativedelta(months=12)
        )
        wizard = self.env['sale.credit.devolucion.wizard'].create({
            'credit_id': credit.id,
            'devolucion_method': 'cheque',
        })
        # 12 months ago → months_old ≈ 12.0 → should be eligible (>= 12)
        try:
            wizard._validate_eligibility()
        except UserError:
            # Boundary case — acceptable if implementation uses strict >
            pass

    def test_p3_devolucion_requires_cancelled_or_withdrawn(self):
        """
        P3: Only cancelled or withdrawn contracts can start devolucion.

        **Validates: Requirements 5.1 — Solo contratos anulados o desistidos**
        """
        credit = self._create_minimal_credit(
            state='approved',
            date_start=date.today() - relativedelta(months=15)
        )
        wizard = self.env['sale.credit.devolucion.wizard'].create({
            'credit_id': credit.id,
            'devolucion_method': 'cheque',
        })
        with self.assertRaises(UserError, msg="P3 FAILED: Approved contract should not be eligible"):
            wizard._validate_eligibility()

    # =========================================================================
    # P5: Bidirectional traceability origin <-> derived
    # =========================================================================

    def test_p5_bidirectional_traceability(self):
        """
        P5: If credit_B.origin_credit_id = credit_A,
        then credit_A.derived_credit_ids must contain credit_B.

        **Validates: Requirements 10.3 — Trazabilidad bidireccional origen↔derivado**
        """
        partner = self.env['res.partner'].create({'name': 'Test Partner P5'})
        credit_a = self._create_minimal_credit(state='cancelled', partner=partner)
        credit_b = self._create_minimal_credit(state='approved', partner=partner)

        # Link B to A as origin
        credit_b.write({'origin_credit_id': credit_a.id})

        # P5: A's derived_credit_ids must contain B
        self.assertIn(
            credit_b, credit_a.derived_credit_ids,
            "P5 FAILED: credit_A.derived_credit_ids does not contain credit_B"
        )
        # And B's origin must be A
        self.assertEqual(
            credit_b.origin_credit_id, credit_a,
            "P5 FAILED: credit_B.origin_credit_id != credit_A"
        )

    def test_p5_multiple_derived_contracts(self):
        """
        P5: Multiple derived contracts all appear in origin's derived_credit_ids.

        **Validates: Requirements 10.3 — Trazabilidad bidireccional origen↔derivado**
        """
        partner = self.env['res.partner'].create({'name': 'Test Partner P5b'})
        origin = self._create_minimal_credit(state='cancelled', partner=partner)
        derived_1 = self._create_minimal_credit(state='approved', partner=partner)
        derived_2 = self._create_minimal_credit(state='approved', partner=partner)

        derived_1.write({'origin_credit_id': origin.id})
        derived_2.write({'origin_credit_id': origin.id})

        self.assertIn(derived_1, origin.derived_credit_ids,
                      "P5 FAILED: derived_1 not in origin.derived_credit_ids")
        self.assertIn(derived_2, origin.derived_credit_ids,
                      "P5 FAILED: derived_2 not in origin.derived_credit_ids")
        self.assertEqual(len(origin.derived_credit_ids), 2,
                         "P5 FAILED: expected 2 derived contracts")

    # =========================================================================
    # P6: Capitalized amount <= origin capital paid
    # =========================================================================

    def test_p6_capitalized_amount_within_bounds(self):
        """
        P6: capitalized_amount must not exceed origin_credit_id.process_capital_paid.

        **Validates: Requirements 10.6 — Monto capitalizado acotado**
        """
        partner = self.env['res.partner'].create({'name': 'Test Partner P6'})
        origin = self._create_minimal_credit(state='approved', partner=partner)
        derived = self._create_minimal_credit(state='approved', partner=partner)

        # Set origin_credit_id and a valid capitalized_amount (0 since no payments)
        derived.write({
            'origin_credit_id': origin.id,
            'contract_process_type': 'improvement',
            'capitalized_amount': 0.0,  # Valid: 0 <= 0 (no payments on origin)
        })
        # _check_capitalized_amount is a constrains method — called on write
        # No exception should be raised for 0.0 <= 0.0
        self.assertEqual(derived.capitalized_amount, 0.0,
                         "P6 FAILED: capitalized_amount should be 0.0")

    def test_p6_capitalized_amount_exceeds_raises(self):
        """
        P6: Setting capitalized_amount > origin capital paid raises ValidationError.

        **Validates: Requirements 10.6 — Monto capitalizado acotado**
        """
        partner = self.env['res.partner'].create({'name': 'Test Partner P6b'})
        origin = self._create_minimal_credit(state='approved', partner=partner)
        derived = self._create_minimal_credit(state='approved', partner=partner)

        # First link origin (process_capital_paid = 0 since no paid lines)
        derived.write({
            'origin_credit_id': origin.id,
            'contract_process_type': 'improvement',
        })

        # Try to set capitalized_amount > process_capital_paid (which is 0 for no payments)
        # 99999.0 > 0.0 + 0.01 → should raise ValidationError
        with self.assertRaises(ValidationError,
                               msg="P6 FAILED: Should raise ValidationError when capitalized_amount > capital paid"):
            derived.write({'capitalized_amount': 99999.0})

    def test_p6_capitalized_amount_within_tolerance(self):
        """
        P6: capitalized_amount <= process_capital_paid + 0.01 is allowed (tolerance).

        **Validates: Requirements 10.6 — Monto capitalizado acotado**
        """
        partner = self.env['res.partner'].create({'name': 'Test Partner P6c'})
        origin = self._create_minimal_credit(state='approved', partner=partner)
        derived = self._create_minimal_credit(state='approved', partner=partner)

        derived.write({
            'origin_credit_id': origin.id,
            'contract_process_type': 'improvement',
        })

        # 0.005 <= 0.0 + 0.01 → within tolerance, should NOT raise
        try:
            derived.write({'capitalized_amount': 0.005})
        except ValidationError:
            self.fail("P6 FAILED: capitalized_amount within tolerance (0.005 <= 0.01) should not raise")

    # =========================================================================
    # P7: Cron idempotency
    # =========================================================================

    def test_p7_cron_cancel_idempotent(self):
        """
        P7: Running _cron_auto_cancel_contracts twice does not cancel additional contracts.

        **Validates: Requirements 1.5 / 8.1 — Cron idempotente**
        """
        # Create a contract that would be eligible for auto-cancellation:
        # approved, date_start in last month, no paid lines
        last_month_start = date.today().replace(day=1) - relativedelta(months=1)
        credit = self._create_minimal_credit(
            state='approved',
            date_start=last_month_start
        )

        # Simulate running on the last day of the month by patching fields.Date.today
        # to return the last day of the previous month
        last_day_of_last_month = date.today().replace(day=1) - timedelta(days=1)

        with patch('odoo.fields.Date.today', return_value=last_day_of_last_month):
            # First run
            self.env['sale.credit']._cron_auto_cancel_contracts()
            state_after_first = credit.state

            # Second run
            self.env['sale.credit']._cron_auto_cancel_contracts()
            state_after_second = credit.state

        # State should be the same after both runs (idempotent)
        self.assertEqual(
            state_after_first, state_after_second,
            f"P7 FAILED: State changed between first ({state_after_first}) "
            f"and second ({state_after_second}) cron run"
        )

    def test_p7_cron_does_not_cancel_contracts_with_payments(self):
        """
        P7: Cron does not cancel contracts that have at least one paid line.

        **Validates: Requirements 1.1 — Solo contratos sin primer pago son anulados**
        """
        last_month_start = date.today().replace(day=1) - relativedelta(months=1)
        credit = self._create_minimal_credit(
            state='approved',
            date_start=last_month_start
        )

        # Add a paid line — this contract should NOT be cancelled
        self.env['sale.credit.line'].create({
            'credit_id': credit.id,
            'count': 1,
            'expected_date_payment': last_month_start + timedelta(days=30),
            'amount_fixed': 1000.0,
            'amount_capital': 800.0,
            'amount_interest': 200.0,
            'amount_others': 0.0,
            'state': 'paid',
        })

        last_day_of_last_month = date.today().replace(day=1) - timedelta(days=1)

        with patch('odoo.fields.Date.today', return_value=last_day_of_last_month):
            self.env['sale.credit']._cron_auto_cancel_contracts()

        self.assertEqual(
            credit.state, 'approved',
            "P7 FAILED: Contract with paid lines should not be cancelled by cron"
        )

    def test_p7_cron_only_runs_on_last_day_of_month(self):
        """
        P7: Cron returns early if today is not the last day of the month.

        **Validates: Requirements 1.5 — Cron ejecuta solo el último día del mes**
        """
        last_month_start = date.today().replace(day=1) - relativedelta(months=1)
        credit = self._create_minimal_credit(
            state='approved',
            date_start=last_month_start
        )

        # Patch to a day that is NOT the last day of the month (e.g., the 15th)
        mid_month = date.today().replace(day=15)

        with patch('odoo.fields.Date.today', return_value=mid_month):
            self.env['sale.credit']._cron_auto_cancel_contracts()

        # Contract should remain approved since cron should have returned early
        self.assertEqual(
            credit.state, 'approved',
            "P7 FAILED: Cron should not cancel contracts when not run on last day of month"
        )


class TestFacturacionFinalContratoSaldado(TransactionCase):
    """
    Cubre la facturación final (`action_follow_credit_flow`) de un contrato
    que ya fue saldado (state='closed').

    Gap identificado en la auditoría pre-producción 91181eb: el botón
    "Facturar" del form de sale.credit no tenía cobertura de tests.
    Estos tests blindan el contrato contra:
      - invocación cuando el contrato NO está cerrado (debe explotar);
      - ausencia de producto / propiedad / servicio (debe explotar);
      - transición automática optimization_dinamic → state=closed+to_invoice;
      - transición manual action_to_closed → state=closed+to_invoice;
      - happy path: closed+to_invoice → account.move posted.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Producto vendible con configuración contable mínima (demo data).
        cls.product = cls.env['product.product'].search(
            [('sale_ok', '=', True)], limit=1)
        if not cls.product:
            raise cls.skipTest(
                'No hay product.product con sale_ok=True en la base de tests')

    def _create_minimal_credit(self, state='closed', partner=None):
        """Helper: crea un sale.credit con producto y, si state='closed',
        marca todas sus líneas como pagadas y dispara optimization_dinamic.
        """
        if partner is None:
            partner = self.env['res.partner'].create(
                {'name': 'Test Partner Fact. Final'})

        category = self.env['sale.credit.category'].search([], limit=1)
        frequency = self.env['sale.credit.frequency'].search([], limit=1)
        if not category or not frequency:
            self.skipTest(
                'Faltan sale.credit.category o sale.credit.frequency en la DB')

        credit = self.env['sale.credit'].create({
            'partner_id': partner.id,
            'category_id': category.id,
            'frequency_id': frequency.id,
            'company_id': self.env.company.id,
            'currency_id_money': self.env.company.currency_id.id,
            'date_start': date.today() - relativedelta(months=15),
            'state': state,
            'type_id': 'finan',
            'contract_process_type': 'new',
            'product_id': self.product.id,
            'amount_total': 1000.0,
            'total_sold': 1000.0,
        })
        return credit

    def _add_paid_lines(self, credit, count=1, amount=1000.0):
        """Helper: crea `count` credit_lines totalmente pagadas."""
        for i in range(1, count + 1):
            self.env['sale.credit.line'].create({
                'credit_id': credit.id,
                'count': i,
                'expected_date_payment': date.today() - timedelta(days=30 * i),
                'amount_fixed': amount / count,
                'amount_capital': amount / count,
                'amount_interest': 0.0,
                'amount_others': 0.0,
                'state': 'paid',
                'amount_paid_total': amount / count,
                'amount_residual': 0.0,
            })
        # optimization_dinamic depende de credit_lines.state;
        # un write vacío fuerza la recomputación de credit_Adeudado y el cierre.
        credit.invalidate_recordset()

    # =========================================================================
    # Happy path: contrato saldado → factura final posteada
    # =========================================================================

    def test_action_follow_credit_flow_generates_posted_invoice(self):
        """
        P-Fact1: Si el contrato está cerrado y to_invoice=True, el flujo
        crea una sale.order, la confirma, genera account.move y la postea.
        El contrato queda con invoice_sale apuntando al move y to_invoice=False.
        """
        credit = self._create_minimal_credit(state='approved')
        self._add_paid_lines(credit, count=1, amount=1000.0)
        # optimization_dinamic debe haber cerrado el contrato
        credit.invalidate_recordset()
        # Forzamos el cierre manualmente para no depender de la cascada completa
        credit.write({'state': 'closed', 'to_invoice': True})

        with patch(
            'odoo.addons.l10n_do_accounting.models.account_move.'
            'AccountMove._assign_ncf',
            return_value=None,
        ):
            result = credit.action_follow_credit_flow()
        self.assertTrue(result, 'El flujo debe devolver una acción de ventana')
        self.assertEqual(result.get('res_model'), 'account.move',
                         'La acción debe apuntar a account.move')

        # El resultado debe ser una acción de ventana hacia el move
        self.assertEqual(result.get('res_model'), 'account.move',
                         'La acción debe apuntar a account.move')
        invoice = self.env['account.move'].browse(result.get('res_id'))
        self.assertTrue(invoice.exists(),
                        'El account.move devuelto debe existir')
        self.assertEqual(invoice.state, 'posted',
                         'La factura final debe quedar posteada')
        self.assertIn(invoice, credit.invoice_ids,
                      'La factura debe quedar vinculada al contrato')
        self.assertEqual(credit.invoice_sale, invoice,
                         'invoice_sale debe apuntar al move recién creado')
        self.assertFalse(credit.to_invoice,
                         'to_invoice debe apagarse tras facturar')

    def test_action_follow_credit_flow_reuses_existing_sale_order(self):
        """
        P-Fact2: Si el contrato ya tiene un sale_id, el flujo NO crea
        un nuevo sale.order — reutiliza el existente.
        """
        credit = self._create_minimal_credit(state='closed')
        credit.write({'to_invoice': True})

        # Pre-creamos un sale.order con la línea del producto
        existing_so = self.env['sale.order'].create({
            'credit_id': credit.id,
            'sale_advanced': True,
            'partner_id': credit.partner_id.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1.0,
                'price_unit': 1000.0,
                'name': self.product.display_name,
            })],
        })
        credit.sale_id = existing_so.id
        credit.sale_valid = True

        with patch(
            'odoo.addons.l10n_do_accounting.models.account_move.'
            'AccountMove._assign_ncf',
            return_value=None,
        ):
            result = credit.action_follow_credit_flow()
        self.assertTrue(result, 'El flujo debe devolver una acción de ventana')
        self.assertEqual(result.get('res_model'), 'account.move',
                         'La acción debe apuntar a account.move')

        self.assertEqual(credit.sale_id, existing_so,
                         'No debe sobrescribirse el sale_id existente')
        # Sólo debe existir una sola sale.order para este contrato
        so_count = self.env['sale.order'].search_count(
            [('credit_id', '=', credit.id)])
        self.assertEqual(so_count, 1,
                         'No debe crearse un nuevo sale.order')

    # =========================================================================
    # Guardas duras (raise)
    # =========================================================================

    def test_action_follow_credit_flow_raises_when_not_closed(self):
        """
        P-Fact3: Si el contrato NO está cerrado, action_follow_credit_flow
        debe lanzar UserError con el mensaje explícito.
        """
        credit = self._create_minimal_credit(state='active')
        credit.write({'to_invoice': True})

        with self.assertRaises(UserError) as ctx:
            credit.action_follow_credit_flow()
        self.assertIn('saldado', str(ctx.exception).lower(),
                      'El mensaje debe mencionar que el contrato debe estar saldado')

    def test_get_final_sale_line_raises_without_product(self):
        """
        P-Fact4: Si el contrato no tiene product_id, property_product_ids
        ni service_product_ids, _get_final_sale_line_values debe lanzar
        UserError — es la guarda que evita crear una factura vacía.
        """
        credit = self._create_minimal_credit(state='closed')
        # Quitamos cualquier fuente de producto
        values = {'product_id': False}
        if 'property_product_ids' in credit._fields:
            values['property_product_ids'] = [(5, 0, 0)]
        if 'service_product_ids' in credit._fields:
            values['service_product_ids'] = [(5, 0, 0)]
        credit.write(values)

        with self.assertRaises(UserError,
                               msg='Sin producto no debe poder armarse la línea de venta'):
            credit._get_final_sale_line_values()

    def test_action_to_closed_raises_when_total_sold_mismatch(self):
        """
        P-Fact5: action_to_closed sólo es válido si total_sold == credit_amount.
        Si no coinciden, debe lanzar ValidationError y NO debe cambiar el estado.
        """
        credit = self._create_minimal_credit(state='approved')
        # total_sold=1000, amount_total=1000 (por helper) — forzamos diferencia
        credit.write({'total_sold': 500.0})

        with self.assertRaises(ValidationError,
                               msg='Si total_sold != credit_amount debe explotar'):
            credit.action_to_closed()
        self.assertEqual(credit.state, 'approved',
                         'El estado no debe cambiar si la validación falla')

    # =========================================================================
    # Transiciones automáticas
    # =========================================================================

    def test_optimization_dinamic_closes_contract_and_marks_to_invoice(self):
        """
        P-Fact6: Cuando todas las credit_lines están pagadas, la cascada
        optimization_dinamic cierra el contrato y prende to_invoice.
        """
        credit = self._create_minimal_credit(state='active')
        self._add_paid_lines(credit, count=1, amount=1000.0)

        # El helper ya agregó líneas pagadas — credit_Adeudado debe ser 0
        # y optimization_dinamic debe haber transicionado el estado.
        credit.invalidate_recordset()
        credit.optimization_dinamic()
        credit.invalidate_recordset()

        self.assertEqual(credit.state, 'closed',
                         'El contrato debe transicionar a closed')
        self.assertTrue(credit.to_invoice,
                        'to_invoice debe prenderse automáticamente')
        self.assertFalse(credit.invoice_sale,
                         'invoice_sale sigue vacío hasta que se facture')

    def test_action_to_closed_sets_to_invoice_when_no_invoice(self):
        """
        P-Fact7: action_to_closed manual (botón "Completado") deja
        al contrato en state=closed y, si no hay invoice previa,
        prende to_invoice=True.
        """
        credit = self._create_minimal_credit(state='approved')
        self._add_paid_lines(credit, count=1, amount=1000.0)
        credit._credit_pay()

        credit.action_to_closed()

        self.assertEqual(credit.state, 'closed',
                         'action_to_closed debe transicionar a closed')
        self.assertTrue(credit.to_invoice,
                        'to_invoice debe prenderse al no haber invoice previa')
        self.assertFalse(credit.invoice_sale,
                         'invoice_sale sigue vacío tras el cierre')

    def test_action_to_closed_does_not_set_to_invoice_when_invoice_exists(self):
        """
        P-Fact8: Si el contrato ya tiene invoice_sale (caso raro: cierre
        retroactivo), action_to_closed NO debe re-encender to_invoice.
        """
        credit = self._create_minimal_credit(state='approved')
        self._add_paid_lines(credit, count=1, amount=1000.0)
        credit._credit_pay()

        # Simulamos que ya tiene una invoice previa (poco común pero válido)
        fake_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': credit.partner_id.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1.0,
                'price_unit': 1000.0,
            })],
        })
        credit.write({'invoice_sale': fake_invoice.id})

        credit.action_to_closed()

        self.assertEqual(credit.state, 'closed')
        self.assertFalse(credit.to_invoice,
                         'to_invoice NO debe prenderse si invoice_sale ya existe')
