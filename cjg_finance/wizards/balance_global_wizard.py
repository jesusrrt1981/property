# -*- coding: utf-8 -*-
"""
F1.2 — Plantilla Global de Balance (XLSX).

Equivalente a ``testarossa/modulos/balance/view/plantilla_global.php``
(662 líneas). Genera un XLSX con todos los oficiales/gerentes
de crédito agrupados por categoría:

    - 1 = Asesores
    - 2 = Gerentes
    - 3 = Gerentes División
    - ALL = Todos

Columnas: Cédula, Nombre, Puesto, Saldo Inicial, Movimientos,
Saldo Final.

La fuente de datos es ``sale.credit`` filtrado por
``oficial_id``/``asesor_id`` y los movimientos vía
``cjg.pos.payment.receipt`` enlazados al contrato.
"""
import base64
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


CATEGORIA_SELECTION = [
    ('1', 'Asesores'),
    ('2', 'Gerentes'),
    ('3', 'Gerentes División'),
    ('ALL', 'Todos'),
]


class BalanceGlobalWizard(models.TransientModel):
    _name = "cjg.finance.balance.global.wizard"
    _description = "Plantilla Global de Balance (XLSX)"

    company_id = fields.Many2one(
        "res.company", string="Compañía",
        required=True, default=lambda s: s.env.company,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)
    categoria = fields.Selection(
        selection=CATEGORIA_SELECTION,
        string="Categoría", required=True, default='ALL',
    )

    def _get_oficial_rows(self):
        """Devuelve lista de dicts con datos de cada oficial
        relevante al filtro de categoría y su balance.

        Estructura de cada row:
            {
                'cedula': str,
                'nombre': str,
                'puesto': str,
                'categoria': '1'|'2'|'3',
                'saldo_inicial': float,
                'movimientos': float,
                'saldo_final': float,
            }
        """
        self.ensure_one()
        User = self.env["res.users"]
        Credit = self.env["sale.credit"]

        domain_users = [("active", "=", True), ("company_ids", "in", self.company_id.id)]
        if self.categoria != 'ALL':
            # Filtramos por grupo de seguridad: 1=asesor, 2=gerente, 3=director
            grupo_xmlid = {
                '1': 'cjg_finance.group_credit_user',
                '2': 'cjg_finance.group_collection_officer',
                '3': 'cjg_finance.group_credit_manager',
            }.get(self.categoria)
            grupo = self.env.ref(grupo_xmlid, raise_if_not_found=False) if grupo_xmlid else None
            if grupo:
                domain_users.append(("group_ids", "in", grupo.id))

        users = User.search(domain_users, order="name asc")
        rows = []
        for user in users:
            credit_domain = [
                ("company_id", "=", self.company_id.id),
                ("oficial_id", "=", user.id),
            ]
            credit_ids = Credit.search(credit_domain).ids
            if not credit_ids:
                continue

            Receipt = self.env["cjg.pos.payment.receipt"]
            pre_domain = [
                ("company_id", "=", self.company_id.id),
                ("state", "!=", "cancelled"),
                ("date", "<", self.date_from),
                ("sale_credit_id", "in", credit_ids),
            ]
            pre = Receipt.search(pre_domain)
            saldo_inicial = sum(pre.mapped("amount_paid"))

            per_domain = [
                ("company_id", "=", self.company_id.id),
                ("state", "!=", "cancelled"),
                ("date", ">=", self.date_from),
                ("date", "<=", self.date_to),
                ("sale_credit_id", "in", credit_ids),
            ]
            per = Receipt.search(per_domain)
            movimientos = sum(per.mapped("amount_paid"))
            saldo_final = saldo_inicial + movimientos

            puesto = self._get_puesto_label(user, self.categoria)
            cedula = user.partner_id.vat or ''
            rows.append({
                'cedula': cedula,
                'nombre': user.name or '',
                'puesto': puesto,
                'categoria': self.categoria if self.categoria != 'ALL' else self._guess_categoria(user),
                'saldo_inicial': saldo_inicial,
                'movimientos': movimientos,
                'saldo_final': saldo_final,
            })
        return rows

    def _get_puesto_label(self, user, categoria):
        if categoria == '1':
            return 'Asesor'
        if categoria == '2':
            return 'Gerente'
        if categoria == '3':
            return 'Gerente División'
        # ALL → adivinar
        return self._guess_categoria_label(user)

    def _guess_categoria(self, user):
        if user.has_group('cjg_finance.group_credit_manager'):
            return '3'
        if user.has_group('cjg_finance.group_collection_officer'):
            return '2'
        return '1'

    def _guess_categoria_label(self, user):
        cat = self._guess_categoria(user)
        return dict(CATEGORIA_SELECTION).get(cat, 'Asesor')

    def _build_xlsx(self, rows):
        if xlsxwriter is None:
            raise UserError(_(
                "La librería xlsxwriter no está disponible en el servidor."
            ))
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Balance Global')

        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'left',
        })
        subtitle_fmt = workbook.add_format({
            'italic': True, 'font_size': 9, 'align': 'left',
            'font_color': '#555555',
        })
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#1976D2', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'text_wrap': True,
        })
        cell_fmt = workbook.add_format({'border': 1, 'align': 'left'})
        num_fmt = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'align': 'right',
        })
        total_label_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#ECEFF1', 'border': 1, 'align': 'left',
        })
        total_num_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#ECEFF1', 'border': 1,
            'num_format': '#,##0.00', 'align': 'right',
        })

        categoria_label = dict(CATEGORIA_SELECTION).get(self.categoria, 'Todos')
        sheet.merge_range(0, 0, 0, 6, _(
            "Balance Global — %s | %s → %s"
        ) % (
            categoria_label,
            fields.Date.to_string(self.date_from),
            fields.Date.to_string(self.date_to),
        ), title_fmt)
        sheet.merge_range(1, 0, 1, 6, _(
            "Compañía: %s"
        ) % (self.company_id.name,), subtitle_fmt)
        sheet.set_row(3, 28)

        headers = [
            _("Cédula"),
            _("Nombre"),
            _("Puesto"),
            _("Saldo Inicial"),
            _("Movimientos"),
            _("Saldo Final"),
        ]
        for col, h in enumerate(headers):
            sheet.write(3, col, h, header_fmt)
        col_widths = [16, 32, 22, 18, 18, 18]
        for col, w in enumerate(col_widths):
            sheet.set_column(col, col, w)

        row_idx = 4
        grouped = {}
        for r in rows:
            grouped.setdefault(r['categoria'], []).append(r)

        total_inicial = 0.0
        total_mov = 0.0
        total_final = 0.0
        for cat_key, cat_rows in grouped.items():
            cat_label = dict(CATEGORIA_SELECTION).get(cat_key, cat_key)
            cat_fmt = workbook.add_format({
                'bold': True, 'bg_color': '#F5F5F5', 'border': 1,
                'align': 'left',
            })
            sheet.merge_range(
                row_idx, 0, row_idx, 5, _("CATEGORÍA: %s") % (cat_label,),
                cat_fmt,
            )
            row_idx += 1
            for r in cat_rows:
                sheet.write(row_idx, 0, r['cedula'] or '', cell_fmt)
                sheet.write(row_idx, 1, r['nombre'] or '', cell_fmt)
                sheet.write(row_idx, 2, r['puesto'] or '', cell_fmt)
                sheet.write_number(row_idx, 3, r['saldo_inicial'] or 0.0, num_fmt)
                sheet.write_number(row_idx, 4, r['movimientos'] or 0.0, num_fmt)
                sheet.write_number(row_idx, 5, r['saldo_final'] or 0.0, num_fmt)
                total_inicial += r['saldo_inicial'] or 0.0
                total_mov += r['movimientos'] or 0.0
                total_final += r['saldo_final'] or 0.0
                row_idx += 1

        if not rows:
            sheet.merge_range(row_idx, 0, row_idx, 5, _(
                "Sin datos para los filtros seleccionados."
            ), cell_fmt)
            row_idx += 1
        else:
            sheet.write(row_idx, 0, _("TOTAL"), total_label_fmt)
            sheet.write(row_idx, 1, '', total_label_fmt)
            sheet.write(row_idx, 2, '', total_label_fmt)
            sheet.write_number(row_idx, 3, total_inicial, total_num_fmt)
            sheet.write_number(row_idx, 4, total_mov, total_num_fmt)
            sheet.write_number(row_idx, 5, total_final, total_num_fmt)
            row_idx += 1

        sheet.merge_range(row_idx + 1, 0, row_idx + 1, 5, _(
            "Oficiales: %d | Σ Inicial: %.2f | Σ Mov: %.2f | Σ Final: %.2f"
        ) % (len(rows), total_inicial, total_mov, total_final), subtitle_fmt)

        workbook.close()
        output.seek(0)
        return output.getvalue()

    def action_export_xlsx(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_(
                "La fecha desde debe ser anterior o igual a la fecha hasta."
            ))
        rows = self._get_oficial_rows()
        xlsx_bytes = self._build_xlsx(rows)
        filename = 'Balance_Global_%s_%s.xlsx' % (
            fields.Date.to_string(self.date_from),
            fields.Date.to_string(self.date_to),
        )
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(xlsx_bytes),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/{}/?download=true'.format(attachment.id),
            'target': 'self',
        }
