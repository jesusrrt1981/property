from odoo import fields, models, api

class SaleCreditCancelWizard(models.TransientModel):
    _name = 'sale.credit.cancel.wizard'
    _description = 'Cancelación de solicitud de credito'


    reason_cancellation = fields.Text(string='Razon de cancelación', required=True)
    cancellation_detail_status = fields.Selection(
        [
            ('standard', 'Cancelación Estándar'),
            ('anulado_devolucion', 'Anulado Devolución'),
        ],
        string='Tipo de Cancelación',
        default='standard',
        required=True,
    )

    def action_confirm(self):
        credit_model = self.env['sale.credit']
        active_id = self._context.get('active_id')
        credit_record = credit_model.browse(active_id)
        today = fields.Date.today()

        reason_cancellation = self.reason_cancellation
        if self.cancellation_detail_status == 'anulado_devolucion':
            credit_record._mark_as_cancelled_by_process(
                'anulado_devolucion',
                notes=reason_cancellation,
            )
        else:
            credit_record.cancelled()

        credit_record.write({'error_log': f'Cancelado por {self.env.user.name}: {reason_cancellation} Fecha de cancelacion {today} '})
