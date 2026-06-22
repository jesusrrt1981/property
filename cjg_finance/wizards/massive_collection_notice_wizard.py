# -*- coding: utf-8 -*-
"""
F2.7 — Aviso de Cobro Masivo (XLSX wizard).

Replica ``testarossa/avisos_de_cobros.php`` (454 líneas) y
``testarossa/modulos/cobros/avisos_de_cobros.php`` en formato XLSX.

Filtros:
    - Oficial
    - Motorizado
    - Fecha reagenda (rango)

Genera un archivo XLSX con el listado de reagenda de cobros,
incluyendo: contrato, cliente, oficial, motorizado, balance,
fecha de reagenda, contacto, etc.
"""
import base64
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class MassiveCollectionNoticeWizard(models.TransientModel):
    _name = 'massive.collection.notice.wizard'
    _description = 'Aviso de Cobro Masivo (XLSX)'

    company_id = fields.Many2one(
        'res.company', string='Compañía',
        required=True, default=lambda s: s.env.company,
    )
    date_from = fields.Date(string='Fecha Reagenda Desde', required=True)
    date_to = fields.Date(string='Fecha Reagenda Hasta', required=True)
    oficial_id = fields.Many2one('res.users', string='Oficial de Cobro')
    motorista_id = fields.Many2one(
        'res.partner', string='Motorizado',
        domain="[('is_motorista', '=', True)]",
    )
    include_calls = fields.Boolean('Incluir solo Llamadas', default=False)
    include_no_calls = fields.Boolean('Incluir solo No Llamadas', default=False)

    def _get_credit_lines(self):
        """Devuelve las líneas de crédito que requieren reagenda.

        La fecha de reagenda la inferimos de la próxima cuota
        pendiente (``expected_date_payment``) que cae dentro del
        rango seleccionado.
        """
        self.ensure_one()
        CreditLine = self.env['sale.credit.line'].sudo()
        domain = [
            ('credit_id.company_id', '=', self.company_id.id),
            ('state', 'not in', ('paid', 'cancelled')),
            ('expected_date_payment', '>=', self.date_from),
            ('expected_date_payment', '<=', self.date_to),
        ]
        if self.oficial_id:
            domain.append(('credit_id.oficial_id', '=', self.oficial_id.id))
        if self.motorista_id:
            domain.append(('credit_id.motorista_id', '=', self.motorista_id.id))
        return CreditLine.search(domain, order='expected_date_payment, credit_id')

    def _build_xlsx(self, lines):
        if xlsxwriter is None:
            raise UserError(_(
                'La librería xlsxwriter no está disponible en el servidor.'))
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Aviso de Cobro Masivo')

        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'left',
        })
        subtitle_format = workbook.add_format({
            'italic': True, 'font_size': 9, 'align': 'left',
            'font_color': '#555555',
        })
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#1976D2', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
            'text_wrap': True,
        })
        cell_format = workbook.add_format({'border': 1, 'align': 'left'})
        date_format = workbook.add_format({
            'border': 1, 'align': 'center', 'num_format': 'dd/mm/yyyy',
        })
        num_format = workbook.add_format({
            'border': 1, 'num_format': '#,##0.00', 'align': 'right',
        })

        sheet.merge_range(0, 0, 0, 9, _(
            'Aviso de Cobro Masivo — Reagenda %s → %s'
        ) % (
            fields.Date.to_string(self.date_from),
            fields.Date.to_string(self.date_to),
        ), title_format)
        sheet.merge_range(1, 0, 1, 9, _(
            'Compañía: %s | Oficial: %s | Motorizado: %s'
        ) % (
            self.company_id.name,
            self.oficial_id.name or 'Todos',
            self.motorista_id.name or 'Todos',
        ), subtitle_format)
        sheet.set_row(3, 28)

        headers = [
            _('Fecha Reagenda'),
            _('Contrato'),
            _('Cliente'),
            _('Cédula/RNC'),
            _('Oficial'),
            _('Motorizado'),
            _('Teléfono'),
            _('Cuota #'),
            _('Monto Cuota'),
            _('Saldo Pendiente'),
        ]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
        col_widths = [14, 16, 30, 16, 22, 22, 16, 10, 14, 16]
        for col, w in enumerate(col_widths):
            sheet.set_column(col, col, w)

        row_idx = 4
        total_lines = 0
        total_amount = 0.0
        total_balance = 0.0
        for line in lines:
            credit = line.credit_id
            partner = credit.partner_id
            # SPRINT COBROS-CRITICOS 2026-06-20 Fix #3g: helper unificado
            # en export de Excel masivo. Antes: solo credit.oficial_id.
            if hasattr(credit, '_get_collection_officer'):
                officer = credit._get_collection_officer()
            else:
                officer = credit.oficial_id or credit.collection_user_id
            sheet.write(row_idx, 0, line.expected_date_payment, date_format)
            sheet.write(row_idx, 1, credit.name or '', cell_format)
            sheet.write(row_idx, 2, partner.name or '', cell_format)
            sheet.write(row_idx, 3, partner.vat or '', cell_format)
            sheet.write(row_idx, 4, officer.name if officer else '', cell_format)
            sheet.write(row_idx, 5, credit.motorista_id.name or '', cell_format)
            sheet.write(row_idx, 6, partner.phone or partner.mobile or '', cell_format)
            sheet.write_number(row_idx, 7, line.count or 0, cell_format)
            sheet.write_number(row_idx, 8, line.amount_fixed or 0.0, num_format)
            sheet.write_number(row_idx, 9, credit.amount_residual or 0.0, num_format)
            total_lines += 1
            total_amount += line.amount_fixed or 0.0
            total_balance += credit.amount_residual or 0.0
            row_idx += 1

        if not lines:
            sheet.merge_range(row_idx, 0, row_idx, 9,
                              _('Sin datos para los filtros seleccionados.'),
                              cell_format)
            row_idx += 1
        else:
            total_label_format = workbook.add_format({
                'bold': True, 'bg_color': '#ECEFF1', 'border': 1, 'align': 'left',
            })
            total_num_format = workbook.add_format({
                'bold': True, 'bg_color': '#ECEFF1', 'border': 1,
                'num_format': '#,##0.00', 'align': 'right',
            })
            total_int_format = workbook.add_format({
                'bold': True, 'bg_color': '#ECEFF1', 'border': 1,
                'num_format': '#,##0', 'align': 'right',
            })
            sheet.write(row_idx, 0, _('TOTAL'), total_label_format)
            for col in range(1, 7):
                sheet.write(row_idx, col, '', total_label_format)
            sheet.write_number(row_idx, 7, total_lines, total_int_format)
            sheet.write_number(row_idx, 8, total_amount, total_num_format)
            sheet.write_number(row_idx, 9, total_balance, total_num_format)
            row_idx += 1

        sheet.merge_range(row_idx + 1, 0, row_idx + 1, 9, _(
            'Líneas reagendadas: %d | Suma cuota: %.2f | Saldo total: %.2f'
        ) % (total_lines, total_amount, total_balance), subtitle_format)

        workbook.close()
        output.seek(0)
        return output.getvalue()

    def action_export_xlsx(self):
        self.ensure_one()
        lines = self._get_credit_lines()
        xlsx_bytes = self._build_xlsx(lines)
        filename = 'Aviso_Cobro_Masivo_%s_%s.xlsx' % (
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
