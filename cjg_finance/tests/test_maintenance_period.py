# -*- coding: utf-8 -*-

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestMaintenancePeriodGeneration(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({'testarossa_em_id': 1})
        cls.partner = cls.env['res.partner'].create({'name': 'Annual maintenance customer'})
        cls.contract = cls.env['maintenance.contract'].create({
            'name': 'MTO-TDD-001',
            'partner_id': cls.partner.id,
            'company_id': cls.company.id,
            'maintenance_fee': 1200,
            'date_start': date(2020, 2, 29),
            'state': 'active',
            'legacy_status_code': 39,
        })

    def test_rejects_year_counts_outside_one_to_five(self):
        for years in (0, 6):
            with self.assertRaises(ValidationError):
                self.contract.generate_annual_periods(years)

    def test_generation_targets_a_stable_one_to_five_year_horizon(self):
        first = self.contract.generate_annual_periods(1)
        self.assertEqual(len(first), 1)
        self.assertEqual(first.due_date, date(2021, 2, 28))
        self.assertEqual((first.concept_code, first.amount, first.sequence), ('106', 1200, 1))

        following = self.contract.generate_annual_periods(5)
        self.assertEqual(len(following), 4)
        self.assertEqual(following.mapped('sequence'), [2, 3, 4, 5])
        self.assertEqual(following[3].due_date, date(2025, 2, 28))
        self.assertFalse(self.contract.generate_annual_periods(5))

    def test_generation_requires_eligible_company_status_and_fee(self):
        cases = [
            ('maintenance_fee', 0),
            ('legacy_status_code', 999),
            ('company_id', self.env['res.company'].create({'name': 'Ineligible'}).id),
        ]
        for field, value in cases:
            original = self.contract[field]
            self.contract[field] = value
            with self.assertRaises(ValidationError):
                self.contract.generate_annual_periods(1)
            self.contract[field] = original.id if field == 'company_id' else original

    def test_exemption_creates_separate_negative_concept_204_row(self):
        self.env['maintenance.exemption.policy'].create({
            'name': 'Legacy exemption',
            'contract_id': self.contract.id,
            'date_from': date(2021, 1, 1),
            'date_to': date(2021, 12, 31),
            'percentage': 100,
        })
        rows = self.contract.generate_annual_periods(1)
        exemption = self.env['maintenance.period'].search([
            ('contract_id', '=', self.contract.id), ('concept_code', '=', '204')])
        self.assertEqual(len(rows), 1)
        self.assertEqual(exemption.amount, -1200)
        self.assertEqual(exemption.sequence, rows.sequence)
        self.assertEqual(rows.net_collectible(), 0)
        rows.mark_paid(self.env['maintenance.contract.payment'])
        movements = self.env['maintenance.period'].search([
            ('contract_id', '=', self.contract.id), ('sequence', '=', 1)])
        self.assertEqual(set(movements.mapped('state')), {'paid'})

    def test_cron_is_idempotent_for_same_anniversary_year(self):
        self.contract.date_start = date.today().replace(year=date.today().year - 3)
        self.env['maintenance.contract'].cron_generate_annual_periods()
        self.env['maintenance.contract'].cron_generate_annual_periods()
        charges = self.env['maintenance.period'].search([
            ('contract_id', '=', self.contract.id), ('concept_code', '=', '106')])
        self.assertEqual(charges.mapped('sequence'), [1, 2, 3])

    def test_pos_lists_pending_period_with_net_exemption_amount(self):
        self.env['maintenance.exemption.policy'].create({
            'name': 'Half exemption', 'contract_id': self.contract.id,
            'date_from': date(2021, 1, 1), 'date_to': date(2021, 12, 31),
            'percentage': 50,
        })
        period = self.contract.generate_annual_periods(1)
        data = self.env['cjg.pos.session'].get_partner_requerimiento_data(
            self.partner.id, maintenance_contract_id=self.contract.id)
        installment = next(row for row in data if row['type'] == 'mto')['installments'][0]
        self.assertEqual(installment['id'], period.id)
        self.assertEqual(installment['source_model'], 'maintenance.period')
        self.assertEqual(installment['amount_original_residual'], 600)
        self.assertEqual(installment['sequence'], 1)

    def test_generation_rolls_back_every_charge_when_a_later_row_fails(self):
        self.env['maintenance.exemption.policy'].create({
            'name': 'Second year exemption',
            'contract_id': self.contract.id,
            'date_from': date(2022, 1, 1),
            'date_to': date(2022, 12, 31),
            'percentage': 100,
        })
        self.env['maintenance.period'].create({
            'contract_id': self.contract.id,
            'sequence': 2,
            'due_date': date(2022, 2, 28),
            'concept_code': '204',
            'amount': -1200,
        })
        with self.assertRaises(Exception):
            self.contract.generate_annual_periods(2)
        charges = self.env['maintenance.period'].search([
            ('contract_id', '=', self.contract.id), ('concept_code', '=', '106')])
        self.assertFalse(charges)
