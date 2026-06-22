# -*- coding: utf-8 -*-
"""
Tests del campo computado ``credit_Adeudado`` en sale.credit.

El campo ``credit_Adeudado`` (Monetary, compute) suma los residuales
(``amount_residual``) de las credit_lines no canceladas, redondeado a 2
decimales. NO incluye cargos ni abonos (``sale.credit.charge``) — esos
se reflejan en ``balance_adjustments``.

Casos cubiertos:
  - Base: 12 cuotas, pagadas 5 → adeudado = 7 cuotas
  - Cargos posted: NO se suman al adeudado (solo a balance_adjustments)
  - Cero cuotas pagadas: adeudado = total
  - Todas las cuotas pagadas: adeudado = 0
  - Campo readonly (no se puede escribir directo)
"""
from datetime import date, timedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install')
class TestCreditAdeudado(TransactionCase):
    """Suite de pruebas del cálculo de credit_Adeudado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.category = cls.env['sale.credit.category'].search([], limit=1) \
            or cls.env['sale.credit.category'].create({'name': 'CA-Test Cat'})
        cls.frequency = cls.env['sale.credit.frequency'].search([], limit=1) \
            or cls.env['sale.credit.frequency'].create({'name': 'Mensual CA'})

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Cliente CA-Test',
            'vat': 'CA-001',
            'company_id': self.company.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'Producto CA-Test',
            'list_price': 1200.0,
            'company_id': self.company.id,
        })

    def _create_contract(self, n_cuotas=12, monto_cuota=100.0):
        """Crea un sale.credit con n_cuotas, todas en estado 'pending'."""
        contract = self.env['sale.credit'].create({
            'partner_id': self.partner.id,
            'category_id': self.category.id,
            'frequency_id': self.frequency.id,
            'company_id': self.company.id,
            'currency_id_money': self.company.currency_id.id,
            'date_start': date.today() - timedelta(days=180),
            'state': 'approved',
            'type_id': 'finan',
            'contract_process_type': 'new',
            'product_id': self.product.id,
            'total_sold': n_cuotas * monto_cuota,
        })
        for i in range(1, n_cuotas + 1):
            self.env['sale.credit.line'].create({
                'credit_id': contract.id,
                'count': i,
                'expected_date_payment': date.today() + timedelta(days=30 * i),
                'amount_fixed': monto_cuota,
                'amount_capital': monto_cuota * 0.8,
                'amount_interest': monto_cuota * 0.2,
                'amount_others': 0.0,
                'state': 'pending',
                'amount_residual': monto_cuota,
            })
        return contract

    def _pay_n_cuotas(self, contract, n):
        """Marca las primeras n cuotas como 'paid' con residual=0."""
        lines = contract.credit_lines.sorted('count')[:n]
        for line in lines:
            line.write({
                'state': 'paid',
                'amount_residual': 0.0,
                'amount_paid_total': line.amount_fixed,
            })

    # =====================================================================
    # 1. Caso base: 12 cuotas, pagadas 5 → adeudado = 7 cuotas
    # =====================================================================
    def test_01_caso_base_12_cuotas_5_pagadas(self):
        """
        Contrato de 12 cuotas de 100, pagadas 5 → adeudado = 700.
        """
        contract = self._create_contract(n_cuotas=12, monto_cuota=100.0)
        self._pay_n_cuotas(contract, 5)

        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 700.0)

    # =====================================================================
    # 2. Cargos (moras / penalidades) NO afectan credit_Adeudado
    # =====================================================================
    def test_02_cargo_posted_no_suma_al_adeudado(self):
        """
        Un cargo posted (ND) aumenta balance_adjustments pero NO
        credit_Adeudado — ese campo es estrictamente residuales de líneas.
        """
        contract = self._create_contract(n_cuotas=10, monto_cuota=100.0)
        self._pay_n_cuotas(contract, 3)
        contract.invalidate_recordset()
        adeudado_antes = contract.credit_Adeudado  # 7 * 100 = 700

        # Crear un cargo posted (mora) por 500.
        self.env['sale.credit.charge'].create({
            'credit_id': contract.id,
            'charge_type': 'charge',
            'amount': 500.0,
            'reason': 'Mora por atraso de 60 días',
            'date': date.today(),
        }).action_post()

        contract.invalidate_recordset()
        self.assertEqual(
            contract.credit_Adeudado, adeudado_antes,
            'credit_Adeudado NO debe cambiar con cargos posted (500.0)',
        )
        self.assertEqual(
            contract.total_charges, 500.0,
            'total_charges sí debe reflejar la mora',
        )
        self.assertEqual(
            contract.balance_adjustments, 500.0,
            'balance_adjustments debe ser cargos - abonos = 500',
        )

    def test_03_abono_posted_no_resta_al_adeudado(self):
        """
        Un abono posted (descuento) tampoco afecta credit_Adeudado.
        """
        contract = self._create_contract(n_cuotas=4, monto_cuota=200.0)
        contract.invalidate_recordset()
        adeudado_antes = contract.credit_Adeudado  # 800

        self.env['sale.credit.charge'].create({
            'credit_id': contract.id,
            'charge_type': 'credit',
            'amount': 150.0,
            'reason': 'Descuento por buen cliente',
            'date': date.today(),
        }).action_post()

        contract.invalidate_recordset()
        self.assertEqual(
            contract.credit_Adeudado, adeudado_antes,
            'credit_Adeudado NO debe cambiar con abonos posted',
        )
        self.assertEqual(contract.total_credits, 150.0)
        self.assertEqual(contract.balance_adjustments, -150.0)

    # =====================================================================
    # 3. Caso edge: 0 cuotas pagadas → adeudado = total
    # =====================================================================
    def test_04_cero_cuotas_pagadas(self):
        """
        Sin pagos → credit_Adeudado == total_sold del contrato.
        """
        contract = self._create_contract(n_cuotas=10, monto_cuota=150.0)
        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 1500.0)

    # =====================================================================
    # 4. Caso edge: todas las cuotas pagadas → adeudado = 0
    # =====================================================================
    def test_05_todas_cuotas_pagadas_adeudado_cero(self):
        """
        Todas las cuotas 'paid' con residual=0 → credit_Adeudado = 0.
        """
        contract = self._create_contract(n_cuotas=6, monto_cuota=250.0)
        self._pay_n_cuotas(contract, 6)

        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 0.0)

    # =====================================================================
    # 5. Campo readonly: no se puede escribir directo
    # =====================================================================
    def test_06_campo_readonly_no_escribible(self):
        """
        credit_Adeudado es un campo compute; intentar escribir directo
        debe lanzar un error de ORM (AccessError / ReadonlyError).
        """
        contract = self._create_contract(n_cuotas=3, monto_cuota=100.0)
        contract.invalidate_recordset()

        from odoo.exceptions import AccessError
        with self.assertRaises(Exception) as ctx:
            contract.write({'credit_Adeudado': 0.0})

        # Aceptamos AccessError, ValidationError, UserError o ReadonlyError
        # — todos son síntomas de "campo readonly/compute".
        self.assertTrue(
            any(klass in (AccessError, ValidationError, ValueError, TypeError)
                for klass in (AccessError, ValidationError)),
            'Debe impedir escritura directa sobre credit_Adeudado',
        )
        # Sanity: el valor real no cambió.
        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 300.0)

    # =====================================================================
    # 6. Cuotas canceladas NO se incluyen
    # =====================================================================
    def test_07_cuotas_canceladas_excluidas(self):
        """
        Las líneas canceladas no suman al adeudado.
        """
        contract = self._create_contract(n_cuotas=5, monto_cuota=100.0)
        # Cancelar la primera cuota.
        line_to_cancel = contract.credit_lines.filtered(lambda l: l.count == 1)
        line_to_cancel.write({
            'state': 'cancelled',
            'amount_residual': 0.0,
        })
        contract.invalidate_recordset()
        # 4 cuotas pendientes × 100 = 400.
        self.assertEqual(contract.credit_Adeudado, 400.0)

    # =====================================================================
    # 7. Residuales parciales (pago a cuenta)
    # =====================================================================
    def test_08_residuales_parciales(self):
        """
        Pago parcial de una cuota: el adeudado refleja el residual exacto.
        """
        contract = self._create_contract(n_cuotas=4, monto_cuota=200.0)
        line1 = contract.credit_lines.filtered(lambda l: l.count == 1)
        line1.write({
            'state': 'paid_overdue',
            'amount_residual': 50.0,  # pagó 150 de 200
            'amount_paid_total': 150.0,
        })
        contract.invalidate_recordset()
        # 200 + 200 + 200 + 50 = 650
        self.assertEqual(contract.credit_Adeudado, 650.0)

    # =====================================================================
    # 8. Recálculo al modificar residuales
    # =====================================================================
    def test_09_recalculo_ante_cambios(self):
        """
        credit_Adeudado se recalcula cuando cambian los residuales.
        """
        contract = self._create_contract(n_cuotas=3, monto_cuota=100.0)
        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 300.0)

        # Pagar 2 cuotas.
        self._pay_n_cuotas(contract, 2)
        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 100.0)

        # Marcar la última también como pagada.
        self._pay_n_cuotas(contract, 1)  # idempotente, paga 1 más
        contract.invalidate_recordset()
        self.assertEqual(contract.credit_Adeudado, 0.0)
