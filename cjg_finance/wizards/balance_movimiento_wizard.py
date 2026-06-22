# -*- coding: utf-8 -*-
"""
F1.3 — Plantilla Movimiento de Balance (XLSX).

Equivalente a ``testarossa/modulos/balance/view/plantilla_movimiento.php``
(536 líneas). Genera un XLSX con los movimientos pre/cierre
asociados a un oficial de crédito en un rango de fechas.

Columnas: Fecha, Docto, Tipo, Concepto, Debe, Haber, Saldo.

Resuelve los movimientos a partir de los recibos
``cjg.pos.payment.receipt`` vinculados a contratos
``sale.credit`` cuyo ``oficial_id`` coincide con el oficial
seleccionado. La columna "Concepto" se forma por la
descripción + nombre del cliente (equivalente al patrón
Testarossa: ``descripcion &nbsp;&nbsp;&nbsp; cliente``).
"""
import base64
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class BalanceMovimientoWizard(models.TransientModel):
    _name = "cjg.finance.balance.movimiento.wizard"
    _description = "Plantilla Movimiento de Balance (XLSX)"

    company_id = fields.Many2one(
        "res.company", string="Compañía",
        required=True, default=lambda s: s.env.company,
    )
    oficial_id = fields.Many2one(
        "res.users", string="Oficial de Crédito",
        required=True,
    )
    date_from = fields.Date(string="Fecha Desde", required=True)
    date_to = fields.Date(string="Fecha Hasta", required=True)

    def _get_movements(self):
        """Devuelve los recibos de los contratos del oficial
        dentro del rango. Ordenados por fecha y docto."""
        self.ensure_one()
        Credit = self.env["sale.credit"]
        credit_ids = Credit.search([
            ("company_id", "=", self.company_id.id),
            ("oficial_id", "=", self.oficial_id.id),
        ]).ids
        if not credit_ids:
            return self.env["cjg.pos.payment.receipt"]
        domain = [
            ("company_id", "=", self.company_id.id),
            ("state", "!=", "cancelled"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("sale_credit_id", "in", credit_ids),
        ]
        return self.env["cjg.pos.payment.receipt"].search(
            domain, order="date asc, name asc",
        )

    def _build_xlsx(self, receipts):
        if xlsxwriter is None:
            raise UserError(_(
                "La librería xlsxwriter no está disponible en el servidor."
            ))
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Balance Movimiento')

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
        date_fmt = workbook.add_format({
            'border': 1, 'align': 'center', 'num_format': 'dd/mm/yyyy',
        })
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

        sheet.merge_range(0, 0, 0, 6, _(
            "Balance de Movimiento — %s"
        ) % (self.oficial_id.name,), title_fmt)
        sheet.merge_range(1, 0, 1, 6, _(
            "Compañía: %s | Período: %s → %s"
        ) % (
            self.company_id.name,
            fields.Date.to_string(self.date_from),
            fields.Date.to_string(self.date_to),
        ), subtitle_fmt)
        sheet.set_row(3, 28)

        headers = [
            _("Fecha"),
            _("Docto"),
            _("Tipo"),
            _("Concepto"),
            _("Debe"),
            _("Haber"),
            _("Saldo"),
        ]
        for col, h in enumerate(headers):
            sheet.write(3, col, h, header_fmt)
        col_widths = [12, 18, 14, 38, 14, 14, 16]
        for col, w in enumerate(col_widths):
            sheet.set_column(col, col, w)

        row_idx = 4
        running = 0.0
        total_debit = 0.0
        total_credit = 0.0
        for r in receipts:
            sheet.write(row_idx, 0, r.date, date_fmt)
            sheet.write(row_idx, 1, r.name or '', cell_fmt)
            tipo = r.concept_id.name if r.concept_id else (r.movement_type or '')
            sheet.write(row_idx, 2, tipo, cell_fmt)
            cliente = r.partner_id.name or ''
            concepto = (r.descripcion or '').strip()
            full_concepto = (concepto + ("  —  " + cliente if cliente else "")).strip(" —")
            sheet.write(row_idx, 3, full_concepto, cell_fmt)
            debe = r.amount_paid if r.amount_paid and r.amount_paid > 0 else 0.0
            haber = -r.amount_paid if r.amount_paid and r.amount_paid < 0 else 0.0
            sheet.write_number(row_idx, 4, debe, num_fmt)
            sheet.write_number(row_idx, 5, haber, num_fmt)
            running += r.amount_paid or 0.0
            sheet.write_number(row_idx, 6, running, num_fmt)
            total_debit += debe
            total_credit += haber
            row_idx += 1

        if not receipts:
            sheet.merge_range(row_idx, 0, row_idx, 6, _(
                "Sin movimientos para el oficial y período seleccionados."
            ), cell_fmt)
            row_idx += 1
        else:
            sheet.write(row_idx, 0, _("TOTAL"), total_label_fmt)
            sheet.write(row_idx, 1, '', total_label_fmt)
            sheet.write(row_idx, 2, '', total_label_fmt)
            sheet.write(row_idx, 3, '', total_label_fmt)
            sheet.write_number(row_idx, 4, total_debit, total_num_fmt)
            sheet.write_number(row_idx, 5, total_credit, total_num_fmt)
            sheet.write_number(row_idx, 6, running, total_num_fmt)
            row_idx += 1

        sheet.merge_range(row_idx + 1, 0, row_idx + 1, 6, _(
            "Movimientos: %d | Σ Debe: %.2f | Σ Haber: %.2f | Saldo: %.2f"
        ) % (len(receipts), total_debit, total_credit, running), subtitle_fmt)

        workbook.close()
        output.seek(0)
        return output.getvalue()

    def action_export_xlsx(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_(
                "La fecha desde debe ser anterior o igual a la fecha hasta."
            ))
        receipts = self._get_movements()
        xlsx_bytes = self._build_xlsx(receipts)
        filename = 'Balance_Movimiento_%s_%s_%s.xlsx' % (
            (self.oficial_id.name or 'oficial').replace(' ', '_'),
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
