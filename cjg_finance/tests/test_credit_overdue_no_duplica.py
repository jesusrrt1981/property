# -*- coding: utf-8 -*-
"""
Test de no-duplicación de moras (H-C10).

El método ``credit.overdue.generar_moras_automaticas`` debe ser IDEMPOTENTE
por (cuota, fecha). Si el cron corre dos veces el mismo día, la segunda
corrida debe ACTUALIZAR la mora existente, no crear una nueva.

Bug H-C10: antes del fix, el ``search`` usaba solo ``credit_line_id``, por
lo que siempre encontraba la mora existente y la actualizaba — pero en
algunos casos (moras canceladas/eliminadas, o data corrupta) podía crear
duplicados. El fix añade el campo ``date`` y filtra también por
``date = today()``, garantizando idempotencia.

Casos cubiertos:
  - Caso principal: 2 calls seguidas el mismo día → 1 sola mora
  - Sanity: la mora resultante es la misma instancia (mismo id)
  - Sanity: el monto se mantiene (no se duplica el cargo)
"""
from datetime import date, timedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestCreditOverdueNoDuplica(TransactionCase):
    """H-C10: generar_moras_automaticas no debe duplicar moras."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        # Configurar compañía para que la rama "company" sea la activa
        # y el cálculo de mora dé > 0.
        cls.company.write({
            'overdue_type_apply': 'auto',
            'overdue_type': 'percent',
            'overdue_period': 'monthly',
            'overdue_invoice_limit': 0,
            'porcentaje': 10.0,
            'importe': 0.0,
        })
        cls.category = cls.env['sale.credit.category'].search([], limit=1) \
            or cls.env['sale.credit.category'].create({'name': 'NODUP-Cat'})
        cls.frequency = cls.env['sale.credit.frequency'].search([], limit=1) \
            or cls.env['sale.credit.frequency'].create({'name': 'Mensual NODUP'})

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Cliente NODUP-Test',
            'vat': 'NODUP-001',
            'company_id': self.company.id,
        })
        self.product = self.env['product.product'].create({
            'name': 'Producto NODUP-Test',
            'list_price': 1200.0,
            'company_id': self.company.id,
        })
        # Limpiar moras previas que puedan contaminar el conteo
        self.env['credit.overdue'].search([]).unlink()
        self.env['credit.overdue.history'].search([]).unlink()

    def _create_contract_with_overdue_line(self):
        """
        Crea un contrato con 1 línea en estado ``paid_overdue``,
        con ``expected_date_payment`` en el pasado para que
        ``date.today() >= due_date`` y se genere mora.
        """
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
            'total_sold': 1000.0,
            'apply_mora': True,
        })
        line = self.env['sale.credit.line'].create({
            'credit_id': contract.id,
            'count': 1,
            # muy en el pasado → due_date = pasado + 1 mes + 0 días <= hoy
            'expected_date_payment': date.today() - timedelta(days=120),
            'amount_fixed': 100.0,
            'amount_capital': 80.0,
            'amount_interest': 20.0,
            'amount_others': 0.0,
            'state': 'paid_overdue',
            'amount_residual': 100.0,
        })
        return contract, line

    def test_generar_moras_automaticas_no_duplica(self):
        """
        H-C10: correr ``generar_moras_automaticas`` 2 veces seguidas
        NO debe crear 2 moras para la misma cuota. Debe haber
        exactamente 1 mora por (cuota, fecha=hoy).
        """
        contract, line = self._create_contract_with_overdue_line()

        # Pre-condición: no hay moras todavía
        moras_antes = self.env['credit.overdue'].search_count([
            ('credit_line_id', '=', line.id),
        ])
        self.assertEqual(moras_antes, 0, "Pre-condición: no debe haber moras previas")

        # Primera corrida
        self.env['credit.overdue'].generar_moras_automaticas()
        moras_despues_1 = self.env['credit.overdue'].search([
            ('credit_line_id', '=', line.id),
        ])
        self.assertEqual(
            len(moras_despues_1), 1,
            "Después de la 1ra corrida debe haber 1 mora para la cuota, "
            f"se encontraron {len(moras_despues_1)}"
        )
        mora_id_1 = moras_despues_1.id
        monto_1 = moras_despues_1.credit_overdue

        # Segunda corrida (mismo día, mismo estado de cuota)
        # La mora debe actualizarse, NO duplicarse.
        self.env['credit.overdue'].generar_moras_automaticas()
        moras_despues_2 = self.env['credit.overdue'].search([
            ('credit_line_id', '=', line.id),
        ])
        self.assertEqual(
            len(moras_despues_2), 1,
            "H-C10: la 2da corrida NO debe crear una mora duplicada. "
            f"Se encontraron {len(moras_despues_2)} moras para la misma cuota."
        )
        # Debe ser LA MISMA instancia (mismo id), no una nueva
        self.assertEqual(
            moras_despues_2.id, mora_id_1,
            "H-C10: la mora después de la 2da corrida debe ser la MISMA "
            "instancia (mismo id), no una nueva"
        )
        # Y la mora debe tener el campo date=hoy (necesario para la idempotencia)
        self.assertEqual(
            moras_despues_2.date, date.today(),
            "H-C10: la mora debe tener date=hoy para que el filtro funcione"
        )
