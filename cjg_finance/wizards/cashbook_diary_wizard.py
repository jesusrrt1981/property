# -*- coding: utf-8 -*-
"""
Diario de Caja / Libro Auxiliar.

Consolida TODOS los movimientos de caja en un rango de fechas.
Equivale al "Libro Auxiliar" contable estándar usado en República Dominicana
para conciliaciones bancarias, arqueos y auditoría fiscal.

Fuentes integradas:
  1. ``account.move.line`` — apuntes contables con cuenta de Caja/Banco.
  2. ``cjg.pos.payment.receipt`` — recibos POS (caja física, no crédito).
  3. ``sale.credit.payment`` — pagos de crédito (hereda de POS receipt
     pero tiene su propia tabla; se listan aparte para evitar perder
     referencias al contrato).
  4. ``cash.box.closing`` — cierres / arqueos de caja.

Cada movimiento se aplana a una tupla ``CashbookLine`` con la misma firma
(fecha, docto, tipo, partner, desc, instrumento, banco, debe, haber, NCF,
cuenta) y luego se consolidan, ordenan y acumulan saldo corrido.
"""
from collections import defaultdict
from datetime import datetime
import io

import xlsxwriter

from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Tipos de cuenta que califican como "caja" (Catálogo de cuentas RD).
CASH_ACCOUNT_TYPES = ('asset_cash', 'liability_current')


class CashbookDiaryWizard(models.TransientModel):
    _name = 'cashbook.diary.wizard'
    _description = 'Diario de Caja / Libro Auxiliar'

    company_id = fields.Many2one(
        'res.company', string='Compañía',
        default=lambda s: s.env.company, required=True,
    )
    date_from = fields.Date(
        string='Desde', required=True,
        default=lambda s: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Hasta', required=True,
        default=fields.Date.today(),
    )
    account_id = fields.Many2one(
        'account.account', string='Cuenta de Caja/Banco',
        domain="[('account_type', 'in', ('asset_cash', 'liability_current'))]",
        help='Si se deja vacío, incluye TODAS las cuentas tipo Caja y Banco '
             'asignadas a la compañía.',
    )
    include_account_lines = fields.Boolean(
        string='Incluir Apuntes Contables (account.move.line)',
        default=True,
        help='Apuntes contables que tocan cuentas de caja/bancos.',
    )
    include_pos = fields.Boolean(
        string='Incluir Recibos POS (cjg.pos.payment.receipt)',
        default=True,
        help='Recibos POS generales (no crédito) con cuenta de caja.',
    )
    include_credit = fields.Boolean(
        string='Incluir Pagos de Crédito (sale.credit.payment)',
        default=True,
        help='Pagos de crédito: cuotas, inicial, mantenimiento, contratos.',
    )
    include_closing = fields.Boolean(
        string='Incluir Cierres de Caja (cash.box.closing)',
        default=True,
    )
    only_posted = fields.Boolean(
        string='Solo asientos contabilizados', default=True,
        help='Si está activo, omite asientos en estado "draft".',
    )
    include_cancelled = fields.Boolean(
        string='Incluir movimientos anulados', default=False,
    )

    # ---------------------------------------------------------------------
    # Constraints
    # ---------------------------------------------------------------------
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise UserError(_("'Desde' no puede ser mayor que 'Hasta'."))

    # ---------------------------------------------------------------------
    # Domain builders
    # ---------------------------------------------------------------------
    def _get_cash_accounts_domain(self):
        """Dominio base para localizar cuentas de caja/bancos de la compañía."""
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('account_type', 'in', list(CASH_ACCOUNT_TYPES)),
        ]
        if self.account_id:
            domain = [('id', '=', self.account_id.id)]
        return domain

    def _get_cash_account_ids(self):
        return self.env['account.account'].search(self._get_cash_accounts_domain()).ids

    # ---------------------------------------------------------------------
    # Saldo inicial (a date_from - 1)
    # ---------------------------------------------------------------------
    def _compute_initial_balance(self, cash_account_ids):
        """Suma del debe - haber de las cuentas de caja ANTES de date_from."""
        self.ensure_one()
        if not cash_account_ids:
            return 0.0
        self.env.cr.execute("""
            SELECT COALESCE(SUM(debit - credit), 0.0) AS balance
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE aml.account_id IN %s
              AND aml.company_id = %s
              AND aml.date < %s
              {posted_clause}
        """.format(
            posted_clause=(
                '' if not self.only_posted else "AND am.state = 'posted'"
            ),
        ), (
            tuple(cash_account_ids),
            self.company_id.id,
            self.date_from,
        ))
        row = self.env.cr.fetchone()
        return row and row[0] or 0.0

    # ---------------------------------------------------------------------
    # Recolectores de movimientos
    # ---------------------------------------------------------------------
    def _collect_account_move_lines(self, cash_account_ids):
        """Apuntes contables (account.move.line) que tocan caja/bancos."""
        self.ensure_one()
        if not self.include_account_lines or not cash_account_ids:
            return []
        domain = [
            ('account_id', 'in', cash_account_ids),
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        if self.only_posted:
            domain.append(('move_id.state', '=', 'posted'))
        if not self.include_cancelled:
            domain.append(('move_id.state', '!=', 'cancel'))

        lines = self.env['account.move.line'].search(
            domain, order='date asc, id asc',
        )
        result = []
        for line in lines:
            move = line.move_id
            partner_name = line.partner_id.name if line.partner_id else (
                move.partner_id.name if move.partner_id else ''
            )
            ncf = ''
            if move and move.move_type in ('out_invoice', 'in_invoice',
                                           'out_refund', 'in_refund'):
                ncf = (getattr(move, 'l10n_latam_document_number', False)
                       or move.ref or '')
            result.append({
                'date': line.date,
                'sort_date': fields.Datetime.to_datetime(
                    datetime.combine(line.date, datetime.min.time())
                ),
                'docto': move.name or '',
                'tipo': dict(
                    move._fields['move_type'].selection
                ).get(move.move_type, move.move_type or ''),
                'partner': partner_name or '',
                'description': line.name or move.ref or '',
                'instrumento': '',
                'banco': '',
                'debe': line.debit or 0.0,
                'haber': line.credit or 0.0,
                'ncf': ncf,
                'cuenta': line.account_id.display_name or '',
                'origen_tipo': 'Asiento Contable',
                'origen_id': move.id,
            })
        return result

    def _collect_pos_receipts(self, cash_account_ids):
        """Recibos POS (cjg.pos.payment.receipt) — excluye los que son de
        crédito (esos van por _collect_credit_payments)."""
        self.ensure_one()
        if not self.include_pos:
            return []
        Receipt = self.env['cjg.pos.payment.receipt']
        # sale.credit.payment hereda de cjg.pos.payment.receipt; con
        # _table separada. Hacemos dos búsquedas y unificamos.
        # Pero para que NO dupliquemos, aquí SOLO traemos recibos cuyo
        # ``_name`` sea exactamente cjg.pos.payment.receipt y NO tengan
        # ``credit_id`` (heurística: el recibo puro de POS no tiene
        # credit_id; el de crédito sí).
        all_receipts = Receipt.search([
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        # Filtra: descarta los que son ``sale.credit.payment`` y los cancelados
        pos_only = all_receipts.filtered(
            lambda r: not r._fields.get('credit_id', False) or not r.credit_id
        )
        if not self.include_cancelled:
            pos_only = pos_only.filtered(lambda r: r.state != 'cancelled')

        # Determina la cuenta del recibo. Si el recibo no toca ninguna de
        # las cuentas de caja seleccionadas, lo descartamos.
        result = []
        cash_set = set(cash_account_ids or [])
        for r in pos_only:
            if not r.journal_id:
                continue
            j_account = r.journal_id.default_account_id
            if self.account_id:
                if not j_account or j_account.id != self.account_id.id:
                    continue
            elif cash_set and (not j_account or j_account.id not in cash_set):
                # Si el usuario no eligió cuenta, aceptar cualquier cuenta
                # de caja; si la cuenta del diario no es de caja, omitir.
                continue
            instrument_name = (
                r.instrument_id.name if r.instrument_id else
                (r.journal_id.name if r.journal_id else '')
            )
            bank_name = r.point_id.name if r.point_id else ''
            result.append({
                'date': r.date.date() if r.date else self.date_to,
                'sort_date': r.date or fields.Datetime.to_datetime(
                    datetime.combine(self.date_to, datetime.max.time())
                ),
                'docto': r.name or '',
                'tipo': dict(r._fields['document_type'].selection).get(
                    r.document_type, r.document_type or '',
                ) if 'document_type' in r._fields else '',
                'partner': r.partner_id.name if r.partner_id else '',
                'description': (r.notes or r.document_name or r.name or ''),
                'instrumento': instrument_name or '',
                'banco': bank_name or '',
                'debe': r.amount_paid or 0.0,
                'haber': 0.0,
                'ncf': r.serie or '',
                'cuenta': (
                    r.journal_id.default_account_id.display_name
                    if r.journal_id and r.journal_id.default_account_id else ''
                ),
                'origen_tipo': 'Recibo POS',
                'origen_id': r.id,
            })
        return result

    def _collect_credit_payments(self, cash_account_ids):
        """Pagos de crédito (sale.credit.payment) — incluye cuotas, inicial,
        contratos, mantenimiento."""
        self.ensure_one()
        if not self.include_credit:
            return []
        Payment = self.env['sale.credit.payment']
        domain = [
            ('company_id', '=', self.company_id.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        if not self.include_cancelled:
            domain.append(('state', '!=', 'cancelled'))
        payments = Payment.search(domain, order='date asc, id asc')

        result = []
        cash_set = set(cash_account_ids or [])
        for p in payments:
            j_account = (
                p.journal_id.default_account_id if p.journal_id else False
            )
            if self.account_id:
                if not j_account or j_account.id != self.account_id.id:
                    continue
            elif cash_set and (not j_account or j_account.id not in cash_set):
                continue
            instrument_name = (
                p.instrument_id.name if p.instrument_id else
                (p.journal_id.name if p.journal_id else '')
            )
            bank_name = p.point_id.name if p.point_id else ''
            contract_name = p.credit_id.name if p.credit_id else ''
            result.append({
                'date': p.date.date() if p.date else self.date_to,
                'sort_date': p.date or fields.Datetime.to_datetime(
                    datetime.combine(self.date_to, datetime.max.time())
                ),
                'docto': p.name or '',
                'tipo': (
                    (p.concept_id.name if p.concept_id else (p.movement_type or ''))
                    if 'movement_type' in p._fields else 'Crédito'
                ),
                'partner': p.partner_id.name if p.partner_id else '',
                'description': (p.notes or '') + (
                    ' | Contrato: %s' % contract_name if contract_name else ''
                ),
                'instrumento': instrument_name or '',
                'banco': bank_name or '',
                'debe': p.amount_paid or 0.0,
                'haber': 0.0,
                'ncf': p.serie or '',
                'cuenta': (
                    p.journal_id.default_account_id.display_name
                    if p.journal_id and p.journal_id.default_account_id else ''
                ),
                'origen_tipo': 'Pago de Crédito',
                'origen_id': p.id,
            })
        return result

    def _collect_closings(self):
        """Cierres / arqueos de caja (cash.box.closing)."""
        self.ensure_one()
        if not self.include_closing:
            return []
        domain = [
            ('company_id', '=', self.company_id.id),
            ('date_closing', '>=', self.date_from),
            ('date_closing', '<=', self.date_to),
        ]
        closings = self.env['cash.box.closing'].search(
            domain, order='date_closing asc, id asc',
        )
        result = []
        for c in closings:
            result.append({
                'date': (c.date_closing.date()
                         if c.date_closing else self.date_to),
                'sort_date': c.date_closing or fields.Datetime.to_datetime(
                    datetime.combine(self.date_to, datetime.max.time())
                ),
                'docto': c.name or '',
                'tipo': 'Cierre de Caja',
                'partner': c.user_id.name if c.user_id else '',
                'description': c.notes or '',
                'instrumento': '',
                'banco': '',
                'debe': 0.0,
                'haber': c.total_cash or 0.0,
                'ncf': '',
                'cuenta': '',
                'origen_tipo': 'Cierre / Arqueo',
                'origen_id': c.id,
            })
        return result

    # ---------------------------------------------------------------------
    # Consolidación
    # ---------------------------------------------------------------------
    def _collect_all_movements(self):
        """Une las 4 fuentes en una lista única."""
        self.ensure_one()
        cash_account_ids = self._get_cash_account_ids()
        movements = []
        movements.extend(self._collect_account_move_lines(cash_account_ids))
        movements.extend(self._collect_pos_receipts(cash_account_ids))
        movements.extend(self._collect_credit_payments(cash_account_ids))
        movements.extend(self._collect_closings())
        # Orden por fecha y desempate por origen
        movements.sort(key=lambda m: (m['sort_date'], m['origen_tipo']))
        return movements, cash_account_ids

    # ---------------------------------------------------------------------
    # Acción principal
    # ---------------------------------------------------------------------
    def action_export_xlsx(self):
        """Genera el XLSX consolidado y lo entrega como descarga."""
        self.ensure_one()

        movements, cash_account_ids = self._collect_all_movements()
        initial_balance = self._compute_initial_balance(cash_account_ids)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(
            "Diario_%s" % self.date_from.strftime('%Y%m')
        )
        sheet.set_column('A:A', 12)  # Fecha
        sheet.set_column('B:B', 18)  # # Docto
        sheet.set_column('C:C', 18)  # Tipo Docto
        sheet.set_column('D:D', 32)  # Cliente/Proveedor
        sheet.set_column('E:E', 40)  # Descripción
        sheet.set_column('F:F', 18)  # Instrumento
        sheet.set_column('G:G', 18)  # Banco/Punto
        sheet.set_column('H:H', 14)  # Debe
        sheet.set_column('I:I', 14)  # Haber
        sheet.set_column('J:J', 14)  # Saldo
        sheet.set_column('K:K', 14)  # NCF
        sheet.set_column('L:L', 24)  # Cuenta
        sheet.set_column('M:M', 20)  # Origen Tipo

        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        subtitle_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#555555',
        })
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#388E3C', 'font_color': 'white',
            'border': 1, 'text_wrap': True, 'valign': 'vcenter',
        })
        initial_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#FFF9C4', 'top': 1, 'bottom': 1,
        })
        money_fmt = workbook.add_format({'num_format': '#,##0.00'})
        money_bold_fmt = workbook.add_format({
            'num_format': '#,##0.00', 'bold': True,
        })
        date_fmt = workbook.add_format({'num_format': 'dd/mm/yyyy'})

        # ── Encabezado del archivo ──
        sheet.write(0, 0, "DIARIO DE CAJA / LIBRO AUXILIAR", title_fmt)
        sheet.write(1, 0, "Compañía: %s" % self.company_id.name, subtitle_fmt)
        sheet.write(
            2, 0,
            "Rango: %s al %s" % (
                self.date_from.strftime('%d/%m/%Y'),
                self.date_to.strftime('%d/%m/%Y'),
            ),
            subtitle_fmt,
        )
        if self.account_id:
            sheet.write(
                3, 0,
                "Cuenta: %s" % self.account_id.display_name,
                subtitle_fmt,
            )

        headers = [
            'Fecha', '# Docto', 'Tipo Docto', 'Cliente/Proveedor',
            'Descripción', 'Instrumento', 'Banco/Punto',
            'Debe', 'Haber', 'Saldo', 'NCF', 'Cuenta', 'Origen',
        ]
        header_row = 5
        for col, h in enumerate(headers):
            sheet.write(header_row, col, h, header_fmt)

        # ── Fila de saldo inicial ──
        row = header_row + 1
        sheet.write(row, 0, '', initial_fmt)
        sheet.write(row, 1, 'SALDO INICIAL', initial_fmt)
        sheet.write(row, 7, initial_balance, money_bold_fmt)
        sheet.write(row, 9, initial_balance, money_bold_fmt)
        running_balance = initial_balance

        # ── Cuerpo ──
        total_debe = 0.0
        total_haber = 0.0
        for m in movements:
            row += 1
            running_balance += (m['debe'] or 0.0) - (m['haber'] or 0.0)
            total_debe += m['debe'] or 0.0
            total_haber += m['haber'] or 0.0
            if m['date']:
                sheet.write_datetime(
                    row, 0,
                    fields.Datetime.to_datetime(
                        datetime.combine(m['date'], datetime.min.time())
                    ),
                    date_fmt,
                )
            else:
                sheet.write(row, 0, '')
            sheet.write(row, 1, m['docto'] or '')
            sheet.write(row, 2, m['tipo'] or '')
            sheet.write(row, 3, m['partner'] or '')
            sheet.write(row, 4, m['description'] or '')
            sheet.write(row, 5, m['instrumento'] or '')
            sheet.write(row, 6, m['banco'] or '')
            sheet.write(row, 7, m['debe'] or 0.0, money_fmt)
            sheet.write(row, 8, m['haber'] or 0.0, money_fmt)
            sheet.write(row, 9, running_balance, money_fmt)
            sheet.write(row, 10, m['ncf'] or '')
            sheet.write(row, 11, m['cuenta'] or '')
            sheet.write(row, 12, m['origen_tipo'] or '')

        # ── Fila de totales ──
        row += 2
        sheet.write(row, 1, 'TOTALES', header_fmt)
        sheet.write(row, 7, total_debe, money_bold_fmt)
        sheet.write(row, 8, total_haber, money_bold_fmt)
        sheet.write(row, 9, running_balance, money_bold_fmt)

        row += 1
        sheet.write(row, 1, 'SALDO FINAL', header_fmt)
        sheet.write(row, 9, running_balance, money_bold_fmt)

        # ── Resumen por origen ──
        row += 3
        sheet.write(row, 0, 'RESUMEN POR ORIGEN', title_fmt)
        row += 1
        resumen_headers = ['Origen', 'Movimientos', 'Total Debe', 'Total Haber']
        for col, h in enumerate(resumen_headers):
            sheet.write(row, col, h, header_fmt)
        by_origin = defaultdict(lambda: {'count': 0, 'debe': 0.0, 'haber': 0.0})
        for m in movements:
            by_origin[m['origen_tipo']]['count'] += 1
            by_origin[m['origen_tipo']]['debe'] += m['debe'] or 0.0
            by_origin[m['origen_tipo']]['haber'] += m['haber'] or 0.0
        for origen, agg in sorted(by_origin.items()):
            row += 1
            sheet.write(row, 0, origen)
            sheet.write(row, 1, agg['count'])
            sheet.write(row, 2, agg['debe'], money_fmt)
            sheet.write(row, 3, agg['haber'], money_fmt)

        # Congelar panel del encabezado
        sheet.freeze_panes(header_row + 1, 0)

        workbook.close()
        output.seek(0)

        filename = "Diario_Caja_%s_al_%s.xlsx" % (
            self.date_from.strftime('%Y%m%d'),
            self.date_to.strftime('%Y%m%d'),
        )
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': output.getvalue().encode('base64'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.'
                        'spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    # ---------------------------------------------------------------------
    # Acción alternativa: previsualizar conteo
    # ---------------------------------------------------------------------
    def action_preview_count(self):
        self.ensure_one()
        movements, _ = self._collect_all_movements()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Movimientos encontrados'),
                'message': _(
                    '%s movimientos en el rango seleccionado.'
                ) % len(movements),
                'type': 'info',
                'sticky': False,
            },
        }
