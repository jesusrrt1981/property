import logging
from odoo import api, fields, models, _
from odoo.tools.misc import format_date
from datetime import datetime, timedelta
from odoo.tools import DEFAULT_SERVER_DATE_FORMAT
from odoo.exceptions import UserError


class Sale_Credit_Followup(models.Model):
    _name = 'sale_credit.followup'
    _description = 'Sale Credit Followup'
    _inherit = ['portal.mixin', 'mail.thread', 'mail.activity.mixin']
    
    name=fields.Char(string='Solicitud')
    respatner=fields.Many2one(string='Cliente',comodel_name='res.partner')
    sale_credit_next_action_date = fields.Date(string='Next reminder', copy=False, company_dependent=True,default=fields.Date.today(), help="The date before which no follow-up action should be taken.")
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user, tracking=True)

   
    unreconciled_aml_ids_sale_credit = fields.One2many('followup.sale.credit',inverse_name='sale_followup_id_line' , readonly=False)
    count_line=fields.Integer(compute='_compute_unreconciled_aml_ids', string='cuotas vencidas')
    
    def _compute_unreconciled_aml_ids(self):
        
        record=self.env['sale.credit'].search([('name','=',self.name)])
        line=self.env['sale.credit.line'].search([('credit_id','=',record.id)])
        list_d=[]
        today = fields.Date.context_today(self)
        for relative in line:
            if  relative.expected_date_payment:
                days_overdue = (today - relative.expected_date_payment).days
            else:
                days_overdue = (relative.date_payment - relative.expected_date_payment).days
                
            data={
                'count':relative.count,
                'amount_residual':relative.amount_residual,
                'credit_id':record.id,
                'expected_date_payment':relative.expected_date_payment,
                'date_payment':relative.date_payment,
                'days_overdue':days_overdue,
                'partner_id':relative.partner_id.id,
                'co_debtor_id':relative.co_debtor_id.id
            }            
            exits=relative.env['followup.sale.credit'].search([('count','=',relative.count),('credit_id','=',record.id)])
            if bool(exits)==False:
                dt=self.unreconciled_aml_ids_sale_credit.create(data)
                list_d.append(dt.id)
            else:
                for list in exits:
                    if relative.count == list.count: 
                        list_d.append(list.id)
        self.unreconciled_aml_ids_sale_credit=list_d
        self.count_line=13
        
    def _compute_days_overdue(self):
        today = fields.Date.context_today(self)
        for order in self:
            print(order)
        

    unpaid_invoice_ids_sale_credit = fields.One2many('sale.credit',inverse_name="sale_followup_id")
    unpaid_invoices_count_sale_credit = fields.Integer(string='cantidad factura')
    unpaid_payment_count_sale_credit = fields.Integer(string='cantidad pago')
    total_due_sale_credit = fields.Float(string='Total Vencido',compute='total_credit')
    def total_credit(self):
        for data_line in self:
            record=data_line.env['sale.credit'].search([('name','=',data_line.name)])
            line=data_line.env['sale.credit.line'].search([('credit_id','=',record.id),('state','=','paid_overdue')])
            precio=[]
            over=[]
            for ls in line:
                precio.append(ls.amount_residual)
                over.append(ls.overdue_residual)
             
            data_line.total_due_sale_credit=(sum(precio)+sum(over))
    total_overdue_sale_credit = fields.Float(string='Total Debido',compute='total_credit_sale')
    def total_credit_sale(self):
        for  data_line in self:
            record=data_line.env['sale.credit'].search([('name','=',data_line.name)])
            line=data_line.env['sale.credit.line'].search([('credit_id','=',record.id),('state','=','pending')])
            precio=[]
            over=[]
            for ls in line:
                precio.append(ls.amount_residual)
                over.append(ls.overdue_residual)
            data_line.total_overdue_sale_credit=(sum(precio)+sum(over))
    followup_status_sale_credit = fields.Selection(
        [('in_need_of_action', 'In need of action'), ('with_overdue_invoices', 'With overdue invoices'), ('no_action_needed', 'No action needed')],
        string='Follow-up Status',
    )
    followup_line_id_sale_credit = fields.Many2one(
        comodel_name='sale_credit.followup.line',
        string="Follow-up Level",
    )
    sale_credit_reminder_type = fields.Selection([('automatico', 'Automatico'), ('manual', 'Manual')], string="recordar", default='automatico')
    type = fields.Selection([('up', 'Follow-up Address sale credit'),('ud','123')])
    followup_responsible_id_sale_credit = fields.Many2one(
        comodel_name='res.users',
        string='Responsible',
        help="Optionally you can assign a user to this field, which will make him responsible for the activities. If empty, we will find someone responsible.",
        tracking=True,
        copy=False,
        company_dependent=True
    )
    credit_id = fields.Many2one('sale.credit', string='Credito', ondelete="cascade", auto_join=True)

class SaleCreditLine(models.Model):
    _name='followup.sale.credit'
    _description = 'Líneas de Seguimiento de Créditos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    internal_notes=fields.Text(string="Description", tracking=True)
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user, tracking=True)
    amount_residual = fields.Float(string="Monto Pendiente",digits=(12,4))
    credit_id = fields.Many2one('sale.credit', string='Credito', ondelete="cascade", auto_join=True)
    co_debtor_id = fields.Many2one('res.partner', string='Codeudor')
    company_id = fields.Many2one(related='credit_id.company_id', store=True, readonly=True)
    count = fields.Integer(string="Contar")
    date_payment = fields.Date(string="Fecha de Pago")
    expected_date_payment = fields.Date(string="Fecha esperada de Pago")
    sale_followup_id_line = fields.Many2one('sale_credit.followup', string='Seguimiento', ondelete="cascade", auto_join=True)
    partner_id = fields.Many2one('res.partner', string="Cliente")

    can_be_dist = fields.Boolean(string='Excluir seguimiento')
    days_overdue = fields.Integer(string='Dias restante' )

    # Campos relacionados para vista de historial
    next_action_date = fields.Date(related='sale_followup_id_line.sale_credit_next_action_date', store=True)
    action_name = fields.Char(related='sale_followup_id_line.followup_line_id_sale_credit.name', store=False)

    # Campos para captura directa en historial
    action_type = fields.Selection(
        [
            ('comment', 'Comentario'),
            ('call', 'Llamada'),
            ('visit', 'Visita'),
            ('email', 'Email')
        ],
        string='Acción',
        default='comment'
    )
    next_contact_date = fields.Date(string='Próximo Contacto')


class SaleCreditLine(models.Model):
    _inherit = 'sale.credit'
    sale_followup_id = fields.Many2one('sale_credit.followup', string='Credito', ondelete="cascade", auto_join=True)

    
