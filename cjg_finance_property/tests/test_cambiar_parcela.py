# -*- coding: utf-8 -*-
"""
Tests del wizard ``cambiar.parcela.wizard``.

Replica el flujo legacy de Testarossa class.Contratos.php::cambiarProducto
para el escenario "Mejora de Parcela":

  1. Validar contrato activo.
  2. Validar que la parcela nueva esté disponible.
  3. Validar que sea misma empresa.
  4. Liberar la parcela vieja (stage='available').
  5. Asignar la parcela nueva (stage='sold').
  6. Actualizar la relación contrato↔parcelas.
  7. Crear un cargo (ND) si costo_cambio > 0.
  8. Auditoría en chatter.

Casos cubiertos:
  - Wizard básico: cambiar parcela de un contrato activo.
  - Savepoint / rollback si algo falla a mitad.
  - Liberación de parcela vieja (stage=available).
  - Asignación de parcela nueva (stage=sold).
  - Creación de cargo (ND) si costo_cambio > 0.
  - NO se crea cargo si costo_cambio = 0.
  - Rechazo misma parcela (vieja == nueva).
  - Rechazo parcela de otra empresa.
"""
from datetime import date, timedelta

from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


@tagged('post_install', '-at_install')
class TestCambiarParcelaWizard(TransactionCase):
    """Suite de pruebas del wizard Cambiar Parcela."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.garden = cls.env['cemetery.garden'].create({
            'name': 'Jardín Test CP',
            'code': 'JCP',
            'space_type': 'parcela',
        })
        cls.phase = cls.env['cemetery.garden'].create  # alias no usado

    def setUp(self):
        super().setUp()
        # Catálogo fase (si no existe demo).
        self.phase_a = self.env['cemetery.phase'].search([('code', '=', 'PA')], limit=1)
        if not self.phase_a:
            self.phase_a = self.env['cemetery.phase'].create({
                'name': 'Fase A Test',
                'code': 'PA',
            })
        self.phase_b = self.env['cemetery.phase'].search([('code', '=', 'PB')], limit=1)
        if not self.phase_b:
            self.phase_b = self.env['cemetery.phase'].create({
                'name': 'Fase B Test',
                'code': 'PB',
            })

        # Empresa secundaria (para test de "otra empresa").
        self.other_company = self.env['res.company'].create({
            'name': 'Empresa Test CP Secundaria',
        })

        # Partner titular.
        self.partner = self.env['res.partner'].create({
            'name': 'Cliente CP-Test',
            'vat': 'CP-001',
            'company_id': self.company.id,
        })

        # Categoría y frecuencia.
        self.category = self.env['sale.credit.category'].search([], limit=1) \
            or self.env['sale.credit.category'].create({'name': 'CP-Test Cat'})
        self.frequency = self.env['sale.credit.frequency'].search([], limit=1) \
            or self.env['sale.credit.frequency'].create({'name': 'Mensual CP'})

        # Contrato activo.
        self.contract = self.env['sale.credit'].create({
            'partner_id': self.partner.id,
            'category_id': self.category.id,
            'frequency_id': self.frequency.id,
            'company_id': self.company.id,
            'currency_id_money': self.company.currency_id.id,
            'date_start': date.today() - timedelta(days=180),
            'state': 'active',
            'type_id': 'finan',
            'contract_process_type': 'new',
        })

        # Parcela vieja: vendida (sold) y asignada al contrato via force_migration
        # (el constraint property_product_ids solo permite 'available' salvo bypass).
        self.parcela_vieja = self.env['property.details'].create({
            'name': 'Parcela Vieja CP',
            'type': 'land',
            'sale_lease': 'for_sale',
            'stage': 'sold',
            'garden_id': self.garden.id,
            'phase_id': self.phase_a.id,
            'block': 'A1',
            'lot': '1',
            'cavities_capacity': 2,
            'price': 1000.0,
            'company_id': self.company.id,
        })
        # Parcela nueva: disponible.
        self.parcela_nueva = self.env['property.details'].create({
            'name': 'Parcela Nueva CP',
            'type': 'land',
            'sale_lease': 'for_sale',
            'stage': 'available',
            'garden_id': self.garden.id,
            'phase_id': self.phase_b.id,
            'block': 'B1',
            'lot': '1',
            'cavities_capacity': 2,
            'price': 1500.0,
            'company_id': self.company.id,
        })
        # Asignar parcela_vieja al contrato (bypass constraint).
        self.contract.with_context(force_migration=True).write({
            'property_product_ids': [(4, self.parcela_vieja.id, 0)],
        })

    # =====================================================================
    # 1. Wizard básico: cambiar parcela de un contrato activo
    # =====================================================================
    def test_01_cambiar_parcela_basico(self):
        """
        Ejecuta el wizard completo y verifica el estado final.
        """
        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 500.0,
            'motivo': 'Cliente solicita mejora a parcela más grande',
        })

        result = wizard.action_cambiar_parcela()

        # La acción retorna vista de la parcela nueva.
        self.assertEqual(result['res_model'], 'property.details')
        self.assertEqual(result['res_id'], self.parcela_nueva.id)

    # =====================================================================
    # 2. Validar savepoint (rollback si falla algo a mitad)
    # =====================================================================
    def test_02_savepoint_rollback_si_falla(self):
        """
        Si una operación intermedia falla (simulado), el savepoint del
        wizard debe hacer rollback y NO debe persistir cambios parciales.
        """
        # Snapshot del estado inicial.
        parcela_vieja_stage_inicial = self.parcela_vieja.stage
        parcela_nueva_stage_inicial = self.parcela_nueva.stage

        # Construir wizard.
        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 100.0,
            'motivo': 'Test savepoint',
        })

        # Simular fallo: parchamos _actualizar_relacion_contrato para que lance
        # una excepción artificial a mitad del savepoint.
        original = wizard._actualizar_relacion_contrato

        def fake_fail(contract, parcela_vieja, parcela_nueva):
            raise UserError('Fallo simulado para test de savepoint')

        wizard._actualizar_relacion_contrato = fake_fail

        # Ejecutar — debe lanzar UserError.
        with self.assertRaises(UserError):
            wizard.action_cambiar_parcela()

        # Restaurar.
        wizard._actualizar_relacion_contrato = original

        # Validar rollback: parcelas deben estar en su estado original.
        self.parcela_vieja.invalidate_recordset()
        self.parcela_nueva.invalidate_recordset()
        self.assertEqual(
            self.parcela_vieja.stage, parcela_vieja_stage_inicial,
            'parcela_vieja debe quedar en su estado original tras rollback',
        )
        self.assertEqual(
            self.parcela_nueva.stage, parcela_nueva_stage_inicial,
            'parcela_nueva debe quedar en su estado original tras rollback',
        )

    # =====================================================================
    # 3. Validar que la parcela vieja se libera (stage=available)
    # =====================================================================
    def test_03_parcela_vieja_se_libera(self):
        """
        Tras ejecutar el wizard, la parcela vieja debe pasar a 'available'
        y limpiar su sold_booking_id.
        """
        # Pre-condición: parcela_vieja está en 'sold'.
        self.assertEqual(self.parcela_vieja.stage, 'sold')

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 0.0,
            'motivo': 'Liberación simple de prueba',
        })
        wizard.action_cambiar_parcela()

        self.parcela_vieja.invalidate_recordset()
        self.assertEqual(
            self.parcela_vieja.stage, 'available',
            'La parcela vieja debe quedar como available',
        )

    # =====================================================================
    # 4. Validar que la parcela nueva se asigna (stage=sold)
    # =====================================================================
    def test_04_parcela_nueva_se_asigna(self):
        """
        Tras ejecutar el wizard, la parcela nueva debe pasar a 'sold'.
        """
        # Pre-condición: parcela_nueva está en 'available'.
        self.assertEqual(self.parcela_nueva.stage, 'available')

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 0.0,
            'motivo': 'Asignación simple de prueba',
        })
        wizard.action_cambiar_parcela()

        self.parcela_nueva.invalidate_recordset()
        self.assertEqual(
            self.parcela_nueva.stage, 'sold',
            'La parcela nueva debe quedar como sold',
        )

    # =====================================================================
    # 5. Validar creación de cargo (ND) si costo_cambio > 0
    # =====================================================================
    def test_05_crea_cargo_si_costo_positivo(self):
        """
        Si costo_cambio > 0, debe crearse un cargo (ND) posted con
        motivo que incluya el display de ambas parcelas.
        """
        nd_count_before = self.env['sale.credit.charge'].search_count([
            ('credit_id', '=', self.contract.id),
        ])

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 750.50,
            'motivo': 'Mejora con cargo de ND',
        })
        wizard.action_cambiar_parcela()

        nd = self.env['sale.credit.charge'].search([
            ('credit_id', '=', self.contract.id),
            ('charge_type', '=', 'charge'),
        ], order='id desc', limit=1)

        self.assertTrue(
            nd.id > 0,
            'Debe existir un cargo creado tras el cambio',
        )
        self.assertEqual(nd.amount, 750.50)
        self.assertEqual(nd.state, 'posted')
        # El motivo referencia el cambio de parcela.
        self.assertIn('Cambio de parcela', nd.reason)
        self.assertIn(self.parcela_vieja.display_name[:5], nd.reason)
        self.assertIn(self.parcela_nueva.display_name[:5], nd.reason)

    # =====================================================================
    # 6. NO se crea cargo si costo_cambio = 0
    # =====================================================================
    def test_06_no_crea_cargo_si_costo_cero(self):
        """
        Si costo_cambio = 0, NO debe crearse cargo (cambio gratuito).
        """
        nd_count_before = self.env['sale.credit.charge'].search_count([
            ('credit_id', '=', self.contract.id),
            ('charge_type', '=', 'charge'),
        ])

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 0.0,
            'motivo': 'Corrección administrativa sin costo',
        })
        wizard.action_cambiar_parcela()

        nd_count_after = self.env['sale.credit.charge'].search_count([
            ('credit_id', '=', self.contract.id),
            ('charge_type', '=', 'charge'),
        ])

        self.assertEqual(
            nd_count_after, nd_count_before,
            'No debe crearse ND cuando costo_cambio = 0',
        )

        # Pero el cambio sí se aplicó.
        self.parcela_vieja.invalidate_recordset()
        self.parcela_nueva.invalidate_recordset()
        self.assertEqual(self.parcela_vieja.stage, 'available')
        self.assertEqual(self.parcela_nueva.stage, 'sold')

    # =====================================================================
    # 7. Rechaza misma parcela (vieja == nueva)
    # =====================================================================
    def test_07_rechaza_misma_parcela(self):
        """
        Si parcela_vieja == parcela_nueva, el constraint
        _check_parcela_nueva_distinct debe lanzar ValidationError al
        crear el wizard (no al ejecutar la acción).
        """
        with self.assertRaises(ValidationError):
            self.env['cambiar.parcela.wizard'].create({
                'contract_id': self.contract.id,
                'parcela_vieja_id': self.parcela_vieja.id,
                'parcela_nueva_id': self.parcela_vieja.id,  # MISMA parcela
                'costo_cambio': 0.0,
                'motivo': 'Intento de auto-asignación',
            })

    # =====================================================================
    # 8. Rechaza parcela de otra empresa
    # =====================================================================
    def test_08_rechaza_parcela_otra_empresa(self):
        """
        Si la parcela nueva pertenece a otra empresa, el wizard debe
        lanzar UserError al ejecutar la acción.
        """
        # Crear parcela de otra empresa.
        parcela_extranjera = self.env['property.details'].create({
            'name': 'Parcela Extranjera',
            'type': 'land',
            'sale_lease': 'for_sale',
            'stage': 'available',
            'garden_id': self.garden.id,
            'phase_id': self.phase_a.id,
            'block': 'Z9',
            'lot': '9',
            'cavities_capacity': 2,
            'price': 1500.0,
            'company_id': self.other_company.id,
        })

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': parcela_extranjera.id,
            'costo_cambio': 0.0,
            'motivo': 'Intento cross-company',
        })

        with self.assertRaises(UserError) as ctx:
            wizard.action_cambiar_parcela()
        self.assertIn('misma empresa', str(ctx.exception).lower())

    # =====================================================================
    # 9. Rechaza parcela no disponible (stage distinto a available/booked)
    # =====================================================================
    def test_09_rechaza_parcela_no_disponible(self):
        """
        Si la parcela nueva no está en 'available' o 'booked', el wizard
        debe lanzar UserError indicando el estado actual.
        """
        # Marcar la parcela nueva como 'sold' directamente.
        self.parcela_nueva.write({'stage': 'sold'})

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 0.0,
            'motivo': 'Parcela ocupada',
        })

        with self.assertRaises(UserError) as ctx:
            wizard.action_cambiar_parcela()
        self.assertIn('no está disponible', str(ctx.exception).lower())

    # =====================================================================
    # 10. Rechaza cambio de parcela en contrato no aprobado/activo
    # =====================================================================
    def test_10_rechaza_contrato_no_aprobado(self):
        """
        Si el contrato no está en 'approved' o 'active', el wizard debe
        lanzar UserError.
        """
        # Pasar el contrato a estado draft.
        self.contract.write({'state': 'draft'})

        wizard = self.env['cambiar.parcela.wizard'].create({
            'contract_id': self.contract.id,
            'parcela_vieja_id': self.parcela_vieja.id,
            'parcela_nueva_id': self.parcela_nueva.id,
            'costo_cambio': 0.0,
            'motivo': 'Test estado',
        })

        with self.assertRaises(UserError) as ctx:
            wizard.action_cambiar_parcela()
        self.assertIn('Aprobado', str(ctx.exception))
