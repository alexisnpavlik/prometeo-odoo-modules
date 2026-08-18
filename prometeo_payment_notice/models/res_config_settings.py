# -*- coding: utf-8 -*-
from odoo import _, fields, models

from .prometeo_payment_notice import (
    PARAM_KEY,
    PARAM_POS_MODE,
    PARAM_TOKEN,
    PARAM_URL,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    prometeo_notice_api_url = fields.Char(
        string="URL de la API de cobranzas",
        config_parameter=PARAM_URL,
        help="Base de la API, sin barra final. Ej: https://cobranzas.prometeolab.com.ar",
    )
    prometeo_notice_instance_key = fields.Char(
        string="Clave de instalación",
        config_parameter=PARAM_KEY,
        help="Identificador de esta instalación en la base de cobranzas.",
    )
    prometeo_notice_token = fields.Char(
        string="Token",
        config_parameter=PARAM_TOKEN,
        help="Token entregado al dar de alta esta instalación.",
    )
    prometeo_notice_pos_mode = fields.Selection(
        selection=[
            ("oculto", "No mostrar en el POS"),
            ("franja", "Franja fija arriba"),
            ("popup", "Aviso al abrir la sesión"),
        ],
        string="Aviso en el POS",
        default="oculto",
        config_parameter=PARAM_POS_MODE,
        help="Dónde mostrar el aviso dentro del Punto de Venta.",
    )

    def action_test_payment_notice(self):
        """Guarda la configuración y consulta la API mostrando el resultado."""
        self.ensure_one()
        self.execute()
        data = self.env["prometeo.payment.notice"].fetch_status()
        if not data:
            mensaje = _("No se pudo consultar la API. Revisá la URL, la clave y el token.")
            tipo = "warning"
        elif data.get("mostrar_aviso"):
            mensaje = _("Conexión OK. Hay un aviso activo: %s", data.get("mensaje", ""))
            tipo = "warning"
        else:
            mensaje = _("Conexión OK. El pago del período figura registrado.")
            tipo = "success"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Aviso de pago"),
                "message": mensaje,
                "type": tipo,
                "sticky": False,
            },
        }
