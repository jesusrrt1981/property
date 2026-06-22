import logging

from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from datetime import timedelta, date

_logger = logging.getLogger(__name__)


class CreditOverdue(models.Model):
    _name = 'credit.overdue'
    _description = 'Credit Overdue'
    
    # _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string="Referencia")
    amount_residual = fields.Float(string="Pendiente")
    amount_total = fields.Float(string="Crédito Total")
    company_id = fields.Many2one('res.company', 'Company', required=True, default=lambda self: self.env.company)
    compute_state = fields.Boolean(string="Compute State")
    credit_id = fields.Many2one('sale.credit', string='Credito',domain="[('name', '=', related_credit_name)]")
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)
    # credit_line_id = fields.Many2one('sale.credit.line', string='Credito')
    credit_line_id = fields.Many2one('sale.credit.line', string='Línea de Crédito', domain="[('credit_id', '=', credit_id)]")

    credit_overdue = fields.Float(string="Moras de Crédito")
    expected_date_payment = fields.Date(string="Fecha esperada de Pago", related="credit_line_id.expected_date_payment")
    date = fields.Date(
        string="Fecha de la mora",
        default=fields.Date.today,
        index=True,
        help="H-C10: Permite idempotencia por (cuota, fecha). Si ya existe "
             "una mora para esta cuota en esta fecha, generar_moras_automaticas "
             "la actualiza en vez de duplicar.",
    )
    has_message = fields.Boolean(string="Has Message")
    history_id = fields.Many2one('credit.overdue.history', string='Historial')
    invoice_id = fields.Many2one('account.move', string="Factura")
    overdue_type = fields.Selection([
        ('percent','Porciento'), 
        ('amount','Importe')], string="Tipo")
    partner_id = fields.Many2one('res.partner', string="Cliente")
    payment_state = fields.Selection(related="invoice_id.state", string="Estado de Pago")
    state = fields.Selection([
        ('draft','Draft'),
        ('pending','Pendientes'),
        ('invoiced','Facturado'),
        ('paid','Pagado'),
        ('exonerated','Exonerado'),
        ('exonerated_percent','Exonerado por porcentaje'),
        ('exonerated_amount','Exonerado por monto fijo'),
        ('cancel','Cancelado')], string="Estado", compute='_compute_state')
    
    user_id = fields.Many2one('res.users', string="Usuario")
    related_credit_name = fields.Char(compute='_get_related_credit_name', store=False)
    invoice_payment_state = fields.Selection(related='invoice_id.payment_state', readonly=True, store=True)
    amount_paid = fields.Float(string="Monto pagado", compute="_compute_amount_paid", store=True)
    overdue_updated = fields.Boolean(string="Mora actualizada", compute="_check_overdue_updated", store=True)
    is_exonerated = fields.Boolean()
    exonerated_percent = fields.Boolean()
    exonerated_amount = fields.Boolean()
    debt_overdue = fields.Float(string="Mora adeudada",)

    @api.depends('credit_line_id')
    def _get_related_credit_name(self):
        for record in self:
            if record.credit_line_id:
                record.related_credit_name = record.credit_line_id.credit_id.name
            else:
                record.related_credit_name = False

    @api.depends('invoice_payment_state')
    def _compute_state(self):
        for record in self:
            if record.invoice_payment_state in ('paid', 'in_payment'):
                record.state = 'paid'
            elif record.is_exonerated:
                record.state = 'exonerated'
            elif record.exonerated_percent:
                record.state = 'exonerated_percent'
            elif record.exonerated_amount:
                record.state = 'exonerated_amount'
            elif record.invoice_id:
                record.state = 'invoiced'
            else:
                record.state = 'draft'

    @api.depends('invoice_id.amount_residual', 'invoice_id.amount_total')
    def _compute_amount_paid(self):
        for record in self:
            if record.invoice_id:
                record.amount_paid = record.invoice_id.amount_total - record.invoice_id.amount_residual
            else:
                record.amount_paid = 0.0

    @api.depends('amount_paid')
    def _check_overdue_updated(self):
        for record in self:
            # Solo actualiza la mora en sale.credit.line si el monto pagado ha cambiado
            if record.amount_paid > 0:
                if not record.invoice_id:
                    record.overdue_updated = False
                    return

                credit_line = record.credit_line_id
                credit_line.write({
                    'overdue_residual': record.invoice_id.amount_residual,
                    'amount_residual': credit_line.amount_residual - record.amount_paid
                })

                record.overdue_updated = True
            elif record.amount_paid < 0:
                _logger.info(
                    "Skipping overdue update for exonerated payment on line %s",
                    record.credit_line_id.id if record.credit_line_id else 'N/A',
                )
                record.overdue_updated = False
            else:
                record.overdue_updated = False


    @api.model
    def update_credit_overdue_status(self, invoice):
        credit_overdue = self.search([('invoice_id', '=', invoice.id)], limit=1)

        if credit_overdue:
            credit_line = credit_overdue.credit_line_id
            credit_line.write({
                'overdue_residual': credit_line.overdue_residual - credit_overdue.credit_overdue
            })
    @api.model
    def generar_moras_automaticas(self):
        credit_lines = self.env['sale.credit.line'].search([
        ('credit_id.state', '=', 'approved'),
        ('state','!=','paid'),
        ('credit_id.apply_mora','=','True'),
        ('state','in',['paid_overdue','paid_reload'])
        ])

        company = self.env.company
        overdue_type_apply = company.overdue_type_apply
        
        if  overdue_type_apply=='manual':
            _logger.info('generar_moras_automaticas: manual mode')
            for credit_line in credit_lines:
                try:
                    with self.env.cr.savepoint():
                        _process_manual_overdue(self, credit_line)
                except Exception:
                    _logger.exception(
                        'Failed to process overdue for credit line %s', credit_line.id
                    )
        else:
            _logger.info('generar_moras_automaticas: company config mode')
            for credit_line in credit_lines:
                try:
                    with self.env.cr.savepoint():
                        _process_company_overdue(self, credit_line)
                except Exception:
                    _logger.exception(
                        'Failed to process overdue for credit line %s', credit_line.id
                    )

    def waive_overdue(self):
        self.ensure_one()
        credit_line = self.credit_line_id
        if not credit_line:
            return False
        waived_amount = abs(credit_line.overdue_residual or 0.0)
        if waived_amount <= 0:
            _logger.info(
                "waive_overdue called on line %s with no pending overdue",
                credit_line.id,
            )
            return False
        update_vals = {
            'overdue_residual': 0.0,
            'amount_residual': max(
                0.0,
                (credit_line.amount_residual or 0.0) - waived_amount,
            ),
        }
        if hasattr(credit_line, 'waived_amount'):
            update_vals['waived_amount'] = (
                (credit_line.waived_amount or 0.0) + waived_amount
            )
        if hasattr(credit_line, 'waived_date'):
            update_vals['waived_date'] = fields.Datetime.now()
        credit_line.write(update_vals)
        self.write({
            'state': 'exonerated',
            'is_exonerated': True,
        })
        if hasattr(self, 'waived_amount'):
            self.write({
                'waived_amount': (self.waived_amount or 0.0) + waived_amount,
            })
        if hasattr(self, 'waived_date'):
            self.write({'waived_date': fields.Datetime.now()})
        return True

    def create_invoice(self):
        self.ensure_one()
        credit_line = self.credit_line_id
        overdue_amount = self.credit_overdue
        invoice = self.env['account.move'].create({
            'partner_id': self.partner_id.id,
            'invoice_date': fields.Date.today(),
            'move_type': 'out_invoice',
            'invoice_line_ids': [(0, 0, {
                'name': f'Moras de crédito {self.name}',
                'product_id': self.company_id.product_overdue.id,
                'quantity': 1,
                'price_unit': overdue_amount,
            })],
        })
        self.write({'invoice_id': invoice.id})
        self.env['credit.overdue.history'].create({
            'name': credit_line.name or "Referencia",
            'company_id': self.env.company.id,
            'user_id': self.env.user.id,
            'overdue_date': date.today(),
            'previous_overdue_amount': (
                credit_line.overdue_residual - overdue_amount
            ),
            'new_overdue_amount': credit_line.overdue_residual,
            'overdue_amount': overdue_amount,
            'credit_line_id': credit_line.id,
            'state': 'invoiced',
        })
        return True

    def action_make_invoice_overdue(self):
        return True

    def action_exoneracion(self):
        self.ensure_one()
        return {
            'name': "Exonerar cuota",
            'type': 'ir.actions.act_window',
            'res_model': 'sale.credit.exoneracion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'active_model': self._name,
            },
        }

    def action_view_overdue_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            return False
        action = self.env.ref('account.action_move_out_invoice_type').read()[0]
        form_view = self.env.ref('account.view_move_form')
        action['views'] = [(form_view.id, 'form')]
        action['res_id'] = self.invoice_id.id
        return action


def _process_manual_overdue(env, credit_line):
    config = credit_line.credit_id.config_mora if credit_line.credit_id.config_mora else None

    if not config:
        config = env['credit.overdue.configuration'].create({
            'name': "MORA AUTOMATICA",
            'client': credit_line.credit_id.user_id.id,
            'user_id': env.user.id,
            'credit_id_id': credit_line.credit_id.id,
            'overdue_period': 'monthly',
            'porcentaje': 5.0,
            'intervalo': 0,
        })
    credit_line.credit_id.write({
        'config_mora': config.id,
    })

    if config.overdue_period == 'weekly':
        due_date = credit_line.expected_date_payment + timedelta(weeks=1) + relativedelta(days=config.intervalo)
    elif config.overdue_period  == 'monthly':
        due_date = credit_line.expected_date_payment + relativedelta(months=1) + relativedelta(days=config.intervalo)
    elif config.overdue_period  == 'yearly':
        due_date = credit_line.expected_date_payment + relativedelta(years=1) + relativedelta(days=config.intervalo)
    elif config.overdue_period == 'daily':
        due_date = credit_line.expected_date_payment + relativedelta(days=1) + relativedelta(days=config.intervalo)
    else:
        _logger.warning("Unknown period: %s", config.overdue_period)

    grace_period = timedelta(days=config.intervalo or 0)

    if credit_line.date_payment:
        grace_end = credit_line.expected_date_payment + grace_period
        if credit_line.date_payment <= grace_end:
            overdue_amount = 0.0
        else:
            overdue_amount = 0.0
    elif date.today() >= due_date:
        overdue_amount = 0.0
        if config.tipo_mora == 'percent':
            overdue_amount = credit_line.amount_fixed * (config.porcentaje / 100)
        elif config.tipo_mora == 'amount':
            overdue_amount = config.importe
    else:
        overdue_amount = 0.0

    CreditOverdue = env['credit.overdue']

    if credit_line.state in ('paid', 'paid_reload') and overdue_amount == 0.0:
        return

    if overdue_amount > 0:
        credit_line.write({
            'overdue_residual': credit_line.overdue_residual + overdue_amount,
            'amount_residual': credit_line.amount_residual + overdue_amount,
            'state': 'paid_reload',
        })

    today = date.today()
    credit_overdue = CreditOverdue.search([
        ('credit_line_id', '=', credit_line.id),
        ('date', '=', today),
    ], limit=1)

    if credit_overdue:
        credit_overdue.write({
            'amount_residual': credit_line.amount_residual,
            'amount_total': credit_line.amount_final,
            'credit_overdue': credit_line.overdue_residual,
            'overdue_type': config.tipo_mora,
        })
        _logger.info(
            "H-C10: Mora ya existe para cuota %s fecha %s (id=%s), actualizada en vez de duplicar",
            credit_line.id, today, credit_overdue.id,
        )
    else:
        CreditOverdue.create({
            'name': credit_line.name or "Referencia",
            'amount_residual': credit_line.amount_residual,
            'amount_total': credit_line.amount_final,
            'credit_id': credit_line.credit_id.id,
            'credit_line_id': credit_line.id,
            'credit_overdue': overdue_amount,
            'overdue_type': config.tipo_mora,
            'partner_id': credit_line.partner_id.id,
            'state': 'draft',
            'user_id': env.user.id,
            'date': today,
        })

    overdue_history = env['credit.overdue.history'].create({
        'name': credit_line.name or "Referencia",
        'company_id': env.company.id,
        'user_id': env.user.id,
        'overdue_date': date.today(),
        'previous_overdue_amount': credit_line.overdue_residual - overdue_amount,
        'new_overdue_amount': credit_line.overdue_residual,
        'overdue_amount': overdue_amount,
        'credit_line_id': credit_line.id,
    })

    CreditOverdue.write({
        'history_id': overdue_history.id
    })


def _process_company_overdue(env, credit_line):
    company_overdue_type = credit_line.credit_id.company_id.overdue_type
    company_overdue_period = credit_line.credit_id.company_id.overdue_period
    company_importe = credit_line.credit_id.company_id.importe
    company_porcentaje = credit_line.credit_id.company_id.porcentaje

    if not company_overdue_type or not company_overdue_period:
        company_overdue_type = 'percent'

    if company_overdue_period == 'weekly':
        due_date = credit_line.expected_date_payment + timedelta(weeks=1) + relativedelta(days=credit_line.credit_id.company_id.overdue_invoice_limit)
    elif company_overdue_period  == 'monthly':
        due_date = credit_line.expected_date_payment + relativedelta(months=1) + relativedelta(days=credit_line.credit_id.company_id.overdue_invoice_limit)
    elif company_overdue_period  == 'yearly':
        due_date = credit_line.expected_date_payment + relativedelta(years=1) + relativedelta(days=credit_line.credit_id.company_id.overdue_invoice_limit)
    elif company_overdue_period == 'daily':
        due_date = credit_line.expected_date_payment + relativedelta(days=1) + relativedelta(days=credit_line.credit_id.company_id.overdue_invoice_limit)
    else:
        _logger.warning("Unknown period: %s", company_overdue_period)

    grace_period = timedelta(days=credit_line.credit_id.company_id.overdue_invoice_limit or 0)

    if credit_line.date_payment:
        grace_end = credit_line.expected_date_payment + grace_period
        if credit_line.date_payment <= grace_end:
            overdue_amount = 0.0
        else:
            overdue_amount = 0.0
    elif date.today() >= due_date:
        overdue_amount = 0.0
        if company_overdue_type == 'percent':
            overdue_amount = credit_line.amount_fixed * (company_porcentaje / 100)
        elif company_overdue_type == 'amount':
            overdue_amount = company_importe
    else:
        overdue_amount = 0.0

    CreditOverdue = env['credit.overdue']

    if credit_line.state in ('paid', 'paid_reload') and overdue_amount == 0.0:
        return

    if overdue_amount > 0:
        credit_line.write({
            'overdue_residual': credit_line.overdue_residual + overdue_amount,
            'amount_residual': credit_line.amount_residual + overdue_amount,
            'state': 'paid_reload',
        })

    today = date.today()
    credit_overdue = CreditOverdue.search([
        ('credit_line_id', '=', credit_line.id),
        ('date', '=', today),
    ], limit=1)

    if credit_overdue:
        credit_overdue.write({
            'amount_residual': credit_line.amount_residual,
            'amount_total': credit_line.amount_final,
            'credit_overdue': credit_line.overdue_residual,
            'overdue_type': company_overdue_type,
        })
        _logger.info(
            "H-C10: Mora ya existe para cuota %s fecha %s (id=%s), actualizada en vez de duplicar",
            credit_line.id, today, credit_overdue.id,
        )
    else:
        CreditOverdue.create({
            'name': credit_line.name or "Referencia",
            'amount_residual': credit_line.amount_residual,
            'amount_total': credit_line.amount_final,
            'credit_id': credit_line.credit_id.id,
            'credit_line_id': credit_line.id,
            'credit_overdue': overdue_amount,
            'overdue_type': company_overdue_type,
            'partner_id': credit_line.partner_id.id,
            'state': 'draft',
            'user_id': env.user.id,
            'date': today,
        })

    overdue_history = env['credit.overdue.history'].create({
        'name': credit_line.name or "Referencia",
        'company_id': env.company.id,
        'user_id': env.user.id,
        'overdue_date': date.today(),
        'previous_overdue_amount': credit_line.overdue_residual - overdue_amount,
        'new_overdue_amount': credit_line.overdue_residual,
        'overdue_amount': overdue_amount,
        'credit_line_id': credit_line.id,
    })

    CreditOverdue.write({
        'history_id': overdue_history.id
    })


class CreditOverdueHistory(models.Model):
    _name = 'credit.overdue.history'
    _description = 'Credit Overdue History'
    
    name = fields.Char(string="Referencia")
    company_id = fields.Many2one('res.company', 'Company', required=True, default=lambda self: self.env.company)
    overdue_count = fields.Integer(string="Contador de Moras")
    overdue_ids = fields.One2many("credit.overdue", "history_id", string="Moras")
    user_id = fields.Many2one('res.users', string="Usuario")
    overdue_date = fields.Date(string="Fecha de mora")
    overdue_amount = fields.Float(string="Monto de Mora")
    previous_overdue_amount = fields.Float(string="Importe de mora anterior")
    new_overdue_amount = fields.Float(string="Nuevo importe de mora")
    credit_line_id = fields.Many2one('sale.credit.line', string='Línea de Crédito', domain="[('credit_id', '=', credit_id)]")
    state = fields.Selection([
    ('draft','Draft'),
    ('pending','Pendientes'),
    ('invoiced','Facturado'),
    ('paid','Pagado'),
    ('exonerated','Exonerado'),
    ('exonerated_percent','Exonerado por porcentaje'),
    ('exonerated_amount','Exonerado por monto fijo'),
    ('cancel','Cancelado')], string="Estado")

    def action_view_credit_overdues(self):
        pass
    
class CreditOverdueConfiguration(models.Model):
    _name = 'credit.overdue.configuration'
    _description = 'Configuración de Mora de Créditos'
    
    name = fields.Char(string="Referencia")
    company_id = fields.Many2one('res.company', 'Company', required=True, default=lambda self: self.env.company)
    intervalo = fields.Integer(string="Dias de gracia:")
    credit_id = fields.One2many('sale.credit', string='Credito',inverse_name='config_mora', domain="[('state', '=', 'approved')]")
    credit_id_id= fields.Many2one('sale.credit', string='Crédito Específico', domain="[('state', '=', 'approved')]")
    user_id = fields.Many2one('res.users', string="Creado por", default=lambda self: self.env.user)    
    client = fields.Many2one('res.partner', string="Cliente")
    MORAS_SELECTION = [
        ('amount', 'Importe'),
        ('percent', 'Porcentaje'),]
    tipo_mora = fields.Selection(MORAS_SELECTION, string="Tipo de Mora", default='percent', required=True)
    importe = fields.Float(string="Importe de mora")
    porcentaje = fields.Float(string="Porcentaje de mora %")
    overdue_period = fields.Selection(
        [
            ('daily', 'Diario'),
            ('weekly', 'Semanal'),
            ('monthly', 'Mensual'),
            ('yearly', 'Anual'),
        ],
        string="Frecuencia de Moras",
    )


    @api.onchange('credit_id')
    def _onchange_credit_id(self):
        if self.credit_id:
            self.client = self.credit_id.partner_id
        else:
            self.client = False


    def action_view_credit_overdues(self):
        pass
    
