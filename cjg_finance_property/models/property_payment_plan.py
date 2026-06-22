# -*- coding: utf-8 -*-
# Copyright 2025 CJG

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PropertyPaymentPlan(models.Model):
    _name = 'property.payment.plan'
    _description = 'Property Payment Plan'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10, help='Used to order payment plans')
    name = fields.Char(string='Plan Name', required=True, translate=True)
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Description', translate=True)
    payment_plan_line_ids = fields.One2many(
        'property.payment.plan.line',
        'payment_plan_id',
        string='Payment Terms'
    )
    total_percentage = fields.Float(
        string='Total Percentage',
        compute='_compute_total_percentage',
        store=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    def unlink(self):
        for rec in self:
            # Prevent deletion if referenced by any property
            ref_count = self.env['property.details'].search_count([
                ('payment_plan_id', '=', rec.id)
            ])
            if ref_count:
                raise ValidationError(
                    _("Cannot delete payment plan because it is referenced by properties"))
        return super(PropertyPaymentPlan, self).unlink()

    @api.depends('payment_plan_line_ids.percentage')
    def _compute_total_percentage(self):
        for rec in self:
            total = sum(line.percentage for line in rec.payment_plan_line_ids)
            rec.total_percentage = total

    @api.constrains('payment_plan_line_ids')
    def _check_total_percentage(self):
        for rec in self:
            if rec.payment_plan_line_ids:
                total = sum(line.percentage for line in rec.payment_plan_line_ids)
                if abs(total - 100.0) > 0.01:  # Usar tolerancia para decimales
                    raise ValidationError(
                        _('Total percentage of payment plan must be equal to 100%. Current total: {:.2f}%').format(total)
                    )

class PropertyPaymentPlanLine(models.Model):
    _name = 'property.payment.plan.line'
    _description = 'Property Payment Plan Line'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    payment_plan_id = fields.Many2one(
        'property.payment.plan',
        string='Payment Plan',
        required=True,
        ondelete='cascade'
    )
    name = fields.Char(string='Description', required=True, translate=True)
    percentage = fields.Float(string='Percentage (%)', required=True, default=0.0)
    payment_type = fields.Selection([
        ('booking', 'Booking'),
        ('days_after_booking', 'Days After Booking'),
        ('construction', 'Construction Milestone'),
        ('handover', 'Handover'),
        ('post_handover', 'Post Handover'),
        ('other', 'Other')
    ], string='Payment Type', required=True, default='booking')
    days_after = fields.Integer(string='Days After Booking', default=0)
    installments = fields.Integer(string='Number of Installments', default=1)
    installment_frequency = fields.Selection([
        ('months_1', 'Monthly'),
        ('months_3', 'Quarterly'),
        ('months_6', 'Half-Yearly'),
        ('months_12', 'Yearly')
    ], string='Installment Frequency')
    note = fields.Text(string='Note', translate=True)

    @api.constrains('percentage')
    def _check_percentage(self):
        for rec in self:
            if rec.percentage < 0 or rec.percentage > 100:
                raise ValidationError(_('Percentage must be between 0 and 100.'))

    @api.onchange('payment_type')
    def _onchange_payment_type(self):
        if self.payment_type != 'days_after_booking':
            self.days_after = 0
        if self.payment_type != 'post_handover':
            self.installments = 1
            self.installment_frequency = False


class PropertyDetails(models.Model):
    _inherit = 'property.details'

    # Note: Payment plan fields are now defined in property_details.py
    # to avoid loading order issues during module upgrade.
    # This class only contains the onchange method for payment plan template loading.

    @api.onchange('payment_plan_id')
    def _onchange_payment_plan_id(self):
        """Load payment plan template lines into custom lines"""
        if self.payment_plan_id and self.payment_plan_id.payment_plan_line_ids:
            # Clear existing custom lines
            self.custom_payment_plan_line_ids = [(5, 0, 0)]

            # Create new custom lines from template
            lines = []
            for line in self.payment_plan_id.payment_plan_line_ids:
                lines.append((0, 0, {
                    'sequence': line.sequence,
                    'name': line.name,
                    'percentage': line.percentage,
                    'payment_type': line.payment_type,
                    'days_after': line.days_after,
                    'installments': line.installments,
                    'installment_frequency': line.installment_frequency,
                    'note': line.note,
                }))
            self.custom_payment_plan_line_ids = lines


class PropertyCustomPaymentPlanLine(models.Model):
    _name = 'property.custom.payment.plan.line'
    _description = 'Property Custom Payment Plan Line'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Sequence', default=10)
    property_id = fields.Many2one(
        'property.details',
        string='Property',
        required=True,
        ondelete='cascade'
    )
    name = fields.Char(string='Description', required=True, translate=True)
    percentage = fields.Float(string='Percentage (%)', required=True, default=0.0)
    amount = fields.Monetary(
        string='Amount',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id'
    )
    payment_type = fields.Selection([
        ('booking', 'Booking'),
        ('days_after_booking', 'Days After Booking'),
        ('construction', 'Construction Milestone'),
        ('handover', 'Handover'),
        ('post_handover', 'Post Handover'),
        ('other', 'Other')
    ], string='Payment Type', required=True, default='booking')
    days_after = fields.Integer(string='Days After Booking', default=0)
    installments = fields.Integer(string='Number of Installments', default=1)
    installment_frequency = fields.Selection([
        ('months_1', 'Monthly'),
        ('months_3', 'Quarterly'),
        ('months_6', 'Half-Yearly'),
        ('months_12', 'Yearly')
    ], string='Installment Frequency')
    note = fields.Text(string='Note', translate=True)
    company_id = fields.Many2one(
        related='property_id.company_id',
        string='Company',
        store=True
    )
    currency_id = fields.Many2one(
        related='property_id.currency_id',
        string='Currency',
        store=True
    )

    @api.depends('percentage', 'property_id.price')
    def _compute_amount(self):
        for rec in self:
            if rec.property_id and rec.property_id.price:
                rec.amount = (rec.percentage / 100.0) * rec.property_id.price
            else:
                rec.amount = 0.0

    @api.constrains('percentage')
    def _check_percentage(self):
        for rec in self:
            if rec.percentage < 0 or rec.percentage > 100:
                raise ValidationError(_('Percentage must be between 0 and 100.'))

    @api.onchange('payment_type')
    def _onchange_payment_type(self):
        if self.payment_type != 'days_after_booking':
            self.days_after = 0
        if self.payment_type != 'post_handover':
            self.installments = 1
            self.installment_frequency = False
