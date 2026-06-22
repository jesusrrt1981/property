# -*- coding: utf-8 -*-
"""
Helpers QWeb para reportes CJG Finance.

Odoo 17 sandbox-ea el módulo ``datetime`` en QWeb como ``wrap_module``
y NO expone ``.now()``/``.utcnow()``. Para poder obtener la fecha/hora
actual desde un template QWeb (``cjg.finance.*.report_document``) sin
truenar, exponemos un modelo abstracto ligero con métodos que retornan
un ``str`` formateado o un ``datetime.date`` localizado al tz del
usuario actual.

Uso en template QWeb::

    <span t-esc="env['cjg.finance.qweb.helper'].now_str('%Y-%m-%d %H:%M')"/>
    <t t-set="today" t-value="env['cjg.finance.qweb.helper'].now_date_obj()"/>
"""
from datetime import datetime

import pytz

from odoo import api, fields, models


class CJGQwebHelper(models.AbstractModel):
    _name = "cjg.finance.qweb.helper"
    _description = "Helpers QWeb para reportes CJG Finance (now localizado)"

    @api.model
    def _localized_now(self):
        """Retorna un ``datetime`` naive en el tz del usuario actual.

        Si el usuario no tiene tz, usa 'UTC'.
        """
        user_tz_name = (self.env.user.tz or "UTC") if self.env.user else "UTC"
        try:
            user_tz = pytz.timezone(user_tz_name)
        except pytz.UnknownTimeZoneError:
            user_tz = pytz.UTC
        utc_now = pytz.UTC.localize(fields.Datetime.now())
        return utc_now.astimezone(user_tz).replace(tzinfo=None)

    @api.model
    def now_str(self, fmt="%Y-%m-%d %H:%M"):
        """Retorna el "ahora" formateado según ``fmt``, localizado al
        tz del usuario. Default: ``'%Y-%m-%d %H:%M'``.
        """
        return self._localized_now().strftime(fmt)

    @api.model
    def now_date_obj(self):
        """Retorna un ``datetime.date`` con el día actual en el tz del
        usuario. Útil para comparaciones en QWeb::

            <t t-if="line.expected_date_payment
                     and line.expected_date_payment
                        &lt; env['cjg.finance.qweb.helper'].now_date_obj()">
        """
        return self._localized_now().date()

    @api.model
    def now_datetime(self):
        """Retorna un ``datetime`` naive con el "ahora" en tz del usuario."""
        return self._localized_now()
