from odoo import models
import logging
import psycopg2

_logger = logging.getLogger(__name__)

class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _on_websocket_closed(self, cookies):
        try:
            super()._on_websocket_closed(cookies)
            self.env.flush_all()
        except (psycopg2.errors.SerializationFailure, psycopg2.errors.DeadlockDetected):
            self.env.cr.rollback()
            _logger.debug("Concurrencia detectada en el cierre de websocket para el usuario %s (ignorado)", self.env.uid)
        except Exception as e:
            _logger.warning("Error no esperado durante el cierre de websocket: %s", e)

    def _update_bus_presence(self, inactivity_period, im_status_ids_by_model):
        try:
            super()._update_bus_presence(inactivity_period, im_status_ids_by_model)
            self.env.flush_all()
        except (psycopg2.errors.SerializationFailure, psycopg2.errors.DeadlockDetected):
            self.env.cr.rollback()
            _logger.debug("Concurrencia detectada en update_presence para el usuario %s (ignorado)", self.env.uid)
        except Exception as e:
            _logger.warning("Error no esperado durante update_presence: %s", e)
