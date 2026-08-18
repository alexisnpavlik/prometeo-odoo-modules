# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Agrega el aviso de pago cacheado a la información de sesión.

        Es el mismo mecanismo con el que Odoo entrega la fecha de expiración
        de la base: el cliente web lo lee sin ningún RPC extra.
        """
        result = super().session_info()
        try:
            result["prometeo_payment_notice"] = self.env["prometeo.payment.notice"].get_notice()
        except Exception as e:
            _logger.warning("Aviso de pago: no se pudo agregar a la sesión (%s)", e)
            result["prometeo_payment_notice"] = {"mostrar": False, "mensaje": ""}
        return result
