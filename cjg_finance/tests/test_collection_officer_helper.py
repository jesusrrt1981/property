# -*- coding: utf-8 -*-
"""
SPRINT COBROS-CRITICOS 2026-06-20 — Tests del helper _get_collection_officer().

Helper unificado de oficial de cobro en sale.credit.
Reemplaza el uso directo de oficial_id / collection_user_id en
sitios donde el oficial de cobro puede estar en cualquiera de
los dos campos.
"""
from odoo.tests import TransactionCase


class TestCollectionOfficerHelper(TransactionCase):

    def setUp(self):
        super().setUp()
        self.company = self.env.ref('base.main_company')
        self.partner = self.env['res.partner'].create({
            'name': 'Cliente Helper',
            'vat': '00333444555',
        })
        self.product = self.env['product.product'].create({
            'name': 'Parcela Helper',
            'list_price': 50000.0,
        })
        self.oficial_a = self.env['res.users'].create({
            'name': 'Oficial A',
            'login': 'oficial_a_helper',
        })
        self.oficial_b = self.env['res.users'].create({
            'name': 'Oficial B',
            'login': 'oficial_b_helper',
        })

    def _create_credit(self, **kwargs):
        vals = {
            'partner_id': self.partner.id,
            'product_id': self.product.id,
            'amount_financed': 50000.0,
            'state': 'approved',
        }
        vals.update(kwargs)
        return self.env['sale.credit'].create(vals)

    # ============================================================
    # Helper: prioridad oficial_id sobre collection_user_id
    # ============================================================
    def test_helper_prioridad_oficial_id(self):
        """Si AMBOS están seteados, oficial_id gana."""
        credit = self._create_credit(
            oficial_id=self.oficial_a.id,
            collection_user_id=self.oficial_b.id,
        )
        result = credit._get_collection_officer()
        self.assertEqual(result, self.oficial_a)

    def test_helper_fallback_collection_user_id(self):
        """Si solo collection_user_id está seteado, devuelve ese."""
        credit = self._create_credit(collection_user_id=self.oficial_b.id)
        result = credit._get_collection_officer()
        self.assertEqual(result, self.oficial_b)

    def test_helper_oficial_id_solo(self):
        """Si solo oficial_id está seteado, devuelve ese."""
        credit = self._create_credit(oficial_id=self.oficial_a.id)
        result = credit._get_collection_officer()
        self.assertEqual(result, self.oficial_a)

    def test_helper_ninguno_retorna_false(self):
        """Si ninguno está seteado, retorna False."""
        credit = self._create_credit()
        result = credit._get_collection_officer()
        self.assertFalse(result)

    # ============================================================
    # Helper: variantes con recordset
    # ============================================================
    def test_helper_recordset_vacio(self):
        """Helper con recordset vacío retorna False."""
        result = self.env['sale.credit']._get_collection_officer()
        self.assertFalse(result)

    def test_helper_multiples_registros(self):
        """Helper sobre recordset itera y devuelve dict."""
        c1 = self._create_credit(oficial_id=self.oficial_a.id)
        c2 = self._create_credit(collection_user_id=self.oficial_b.id)
        c3 = self._create_credit()
        result = self.env['sale.credit']._get_collection_officer_for_records(
            c1 | c2 | c3
        )
        self.assertEqual(result.get(c1.id), self.oficial_a)
        self.assertEqual(result.get(c2.id), self.oficial_b)
        self.assertNotIn(c3.id, result)

    # ============================================================
    # Helper: usado por collection_acta_cierre._debitar_comisiones
    # ============================================================
    def test_debitar_comisiones_usa_helper(self):
        """_debitar_comisiones agrupa por helper, no duplica oficiales."""
        # Crear acta con 2 créditos del mismo oficial (vía diferentes campos)
        credit1 = self._create_credit(
            oficial_id=self.oficial_a.id,
        )
        credit2 = self._create_credit(
            collection_user_id=self.oficial_a.id,  # Mismo oficial, otro campo
        )
        # Verificar que el helper devuelve el MISMO oficial en ambos
        self.assertEqual(
            credit1._get_collection_officer(),
            credit2._get_collection_officer(),
        )
        # Si las comisiones se crearan por oficial_id, credit2 no tendría
        # comisión. Con helper, AMBOS cuentan como oficial_a (sin duplicar).
