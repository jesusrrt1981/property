# -*- coding: utf-8 -*-

from odoo import models


class PropertyDetails(models.Model):
    _inherit = 'property.details'

    def _portal_user_can_upload_image(self, user):
        """Only property officers in an allowed company may upload images."""
        self.ensure_one()
        if not user or not user.exists() or not user._is_internal():
            return False
        if not (
            user.has_group('cjg_finance_property.property_rental_officer')
            or user.has_group('cjg_finance_property.property_rental_manager')
        ):
            return False
        return not self.company_id or self.company_id in user.company_ids
