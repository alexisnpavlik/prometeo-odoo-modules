# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    def _load_pos_data(self, data):
        """Agrega el aviso de pago a los datos de la sesión del POS.

        Se inyectan claves sueltas en el registro de pos.session, igual que
        hace el core con _has_cash_move_perm: llegan al frontend sin tocar
        _load_pos_data_fields de pos.config. Cualquier error al leer el
        aviso se ignora: el cartel es accesorio y nunca puede impedir que
        el POS abra.
        """
        result = super()._load_pos_data(data)
        try:
            if not result.get("data"):
                return result
            notice = self.env["prometeo.payment.notice"].get_notice()
            mode = self.env["prometeo.payment.notice"].get_pos_mode()
            result["data"][0]["prometeo_notice_show"] = bool(notice["mostrar"]) and mode != "oculto"
            result["data"][0]["prometeo_notice_message"] = notice["mensaje"]
            result["data"][0]["prometeo_notice_mode"] = mode
        except Exception as e:
            _logger.warning("Aviso de pago: no se pudo agregar a los datos del POS (%s)", e)
        return result
