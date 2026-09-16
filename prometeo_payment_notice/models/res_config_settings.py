# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models

from .prometeo_payment_notice import (
    DIAS_CACHE_VALIDA,
    PARAM_KEY,
    PARAM_POS_MODE,
    PARAM_STATE,
    PARAM_TOKEN,
    PARAM_URL,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    prometeo_notice_api_url = fields.Char(
        string="URL de la API de cobranzas",
        config_parameter=PARAM_URL,
        help="Base de la API, sin barra final. Ej: https://registropagos.prometeolab.com.ar",
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

    prometeo_notice_info_estado = fields.Char(
        string="Estado del pago",
        readonly=True,
        compute="_compute_prometeo_notice_info",
    )
    prometeo_notice_info_bloqueo = fields.Char(
        string="Bloqueo de caja",
        readonly=True,
        compute="_compute_prometeo_notice_info",
    )
    prometeo_notice_info_consulta = fields.Char(
        string="Última consulta exitosa",
        readonly=True,
        compute="_compute_prometeo_notice_info",
    )
    prometeo_notice_info_mensaje = fields.Text(
        string="Mensaje que ve el cliente",
        readonly=True,
        compute="_compute_prometeo_notice_info",
    )
    prometeo_notice_info_crudo = fields.Text(
        string="Respuesta cruda",
        readonly=True,
        compute="_compute_prometeo_notice_info",
    )

    @api.depends("prometeo_notice_pos_mode")
    def _compute_prometeo_notice_info(self):
        """Resume la última respuesta cacheada de la API, sin consultarla.

        Es informativo: lo que se muestra acá es exactamente lo que el módulo
        está usando en este momento para decidir el aviso y el bloqueo.
        """
        notice = self.env["prometeo.payment.notice"]
        raw = notice._get_param(PARAM_STATE)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}

        consultado_el = data.get("consultado_el")
        vigente = notice._cache_vigente(consultado_el)
        for settings in self:
            settings.prometeo_notice_info_estado = self._resumir_estado(data)
            settings.prometeo_notice_info_bloqueo = self._resumir_bloqueo(data, vigente)
            settings.prometeo_notice_info_consulta = self._resumir_consulta(consultado_el)
            settings.prometeo_notice_info_mensaje = data.get("mensaje") or ""
            settings.prometeo_notice_info_crudo = (
                json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) if data else ""
            )

    def _resumir_estado(self, data):
        """Traduce al_dia, dias_atraso y meses_adeudados a una sola línea."""
        if not data:
            return _("Sin datos: todavía no hubo una consulta exitosa.")
        if data.get("al_dia"):
            return _("Al día. El pago del período figura registrado.")
        partes = [_("%s días de atraso", data.get("dias_atraso", 0))]
        meses = data.get("meses_adeudados") or 0
        if meses > 1:
            partes.append(_("%s meses pendientes", meses))
        if not data.get("mostrar_aviso"):
            partes.append(_("todavía sin aviso: dentro del período de gracia"))
        return " · ".join(partes)

    def _resumir_bloqueo(self, data, vigente):
        """Explica si la caja está trabada y por qué, cuando no lo está."""
        if not data:
            return _("Sin bloqueo.")
        if not data.get("bloqueo_caja"):
            return _("Sin bloqueo. El servidor no lo pidió para esta instalación.")
        if not vigente:
            return _(
                "Pedido por el servidor, pero apagado: la última consulta exitosa "
                "tiene %s días o más.",
                DIAS_CACHE_VALIDA,
            )
        return _(
            "Activo: %s segundos de espera al abrir y al cerrar la caja.",
            data.get("bloqueo_caja_segundos", 0),
        )

    def _resumir_consulta(self, consultado_el):
        """Fecha de la última consulta exitosa en hora local, con la antigüedad."""
        if not consultado_el:
            return _("Nunca")
        try:
            consultado = fields.Datetime.to_datetime(consultado_el)
        except (TypeError, ValueError):
            return _("Fecha ilegible: %s", consultado_el)
        if not consultado:
            return _("Nunca")
        local = fields.Datetime.context_timestamp(self, consultado)
        minutos = int((fields.Datetime.now() - consultado).total_seconds() // 60)
        if minutos < 60:
            antiguedad = _("hace %s minutos", max(minutos, 0))
        elif minutos < 60 * 48:
            antiguedad = _("hace %s horas", minutos // 60)
        else:
            antiguedad = _("hace %s días", minutos // (60 * 24))
        return "%s · %s" % (local.strftime("%d/%m/%Y %H:%M"), antiguedad)

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
