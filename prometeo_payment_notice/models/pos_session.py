# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _load_pos_data(self, data):
        """Agrega el aviso de pago a los datos de la sesión del POS.

        Se inyectan claves sueltas en el registro de pos.session, igual que
        hace el core con _has_cash_move_perm: llegan al frontend sin tocar
        _load_pos_data_fields de pos.config.
        """
        result = super()._load_pos_data(data)
        notice = self.env["prometeo.payment.notice"].get_notice()
        mode = self.env["prometeo.payment.notice"].get_pos_mode()
        result["data"][0]["prometeo_notice_show"] = bool(notice["mostrar"]) and mode != "oculto"
        result["data"][0]["prometeo_notice_message"] = notice["mensaje"]
        result["data"][0]["prometeo_notice_mode"] = mode
        return result
