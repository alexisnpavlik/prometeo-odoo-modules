# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PARAM_URL = "prometeo_payment_notice.api_url"
PARAM_KEY = "prometeo_payment_notice.instance_key"
PARAM_TOKEN = "prometeo_payment_notice.token"
PARAM_POS_MODE = "prometeo_payment_notice.pos_mode"
PARAM_STATE = "prometeo_payment_notice.state"

TIMEOUT = 10
SIN_AVISO = {"mostrar": False, "mensaje": ""}


class PrometeoPaymentNotice(models.AbstractModel):
    _name = "prometeo.payment.notice"
    _description = "Aviso de pago del servicio"

    @api.model
    def _get_param(self, key, default=""):
        """Lee un parámetro del sistema con sudo y default seguro."""
        return self.env["ir.config_parameter"].sudo().get_param(key, default) or default

    @api.model
    def fetch_status(self):
        """Consulta la API de cobranzas y cachea la respuesta.

        Devuelve el dict crudo de la API, o {} si no está configurado o la
        consulta falla. Ante error se conserva el último estado cacheado.
        """
        url = self._get_param(PARAM_URL)
        instance_key = self._get_param(PARAM_KEY)
        token = self._get_param(PARAM_TOKEN)
        if not (url and instance_key and token):
            _logger.info("Aviso de pago: módulo sin configurar, no se consulta")
            return {}

        try:
            response = requests.get(
                "%s/v1/status" % url.rstrip("/"),
                headers={"X-Instance-Key": instance_key, "X-Token": token},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            _logger.warning("Aviso de pago: falló la consulta de estado (%s)", e)
            return {}

        data["consultado_el"] = fields.Datetime.to_string(fields.Datetime.now())
        self.env["ir.config_parameter"].sudo().set_param(PARAM_STATE, json.dumps(data))
        _logger.info("Aviso de pago: estado actualizado (aviso=%s)", data.get("mostrar_aviso"))
        return data

    @api.model
    def get_notice(self):
        """Devuelve el aviso a mostrar según el último estado cacheado.

        Fail-safe: si no hay caché o está corrupta, no se muestra nada.
        """
        raw = self._get_param(PARAM_STATE)
        if not raw:
            return dict(SIN_AVISO)
        try:
            data = json.loads(raw)
        except ValueError:
            _logger.warning("Aviso de pago: estado cacheado ilegible, se ignora")
            return dict(SIN_AVISO)
        if not isinstance(data, dict):
            _logger.warning("Aviso de pago: estado cacheado no es un objeto, se ignora")
            return dict(SIN_AVISO)
        return {
            "mostrar": bool(data.get("mostrar_aviso")),
            "mensaje": data.get("mensaje") or "",
        }

    @api.model
    def get_pos_mode(self):
        """Modo de visualización en el POS: oculto, franja o popup."""
        return self._get_param(PARAM_POS_MODE, "oculto")

    @api.model
    def cron_check(self):
        """Punto de entrada del cron diario."""
        self.fetch_status()
