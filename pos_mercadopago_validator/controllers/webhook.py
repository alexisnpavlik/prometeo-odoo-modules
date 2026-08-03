import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MercadoPagoWebhook(http.Controller):
    """Endpoint público de notificaciones de Mercado Pago.

    En integraciones de QR no se puede validar el origen por x-Signature, así que
    el endpoint se asume alcanzable por cualquiera en internet. La defensa no es
    autenticar el origen sino desconfiar del contenido: del cuerpo se lee
    únicamente el identificador del pago, y todo lo demás se resuelve contra la
    API con credenciales propias.
    """

    @http.route(
        "/pos_mercadopago_validator/notification",
        type="http", auth="public", methods=["POST"], csrf=False, save_session=False,
    )
    def notification(self, **kwargs):
        """Responde 200 siempre; procesa sólo si el payload trae un id usable."""
        payload = request.get_json_data() if request.httprequest.data else None
        payment_id = ((payload or {}).get("data") or {}).get("id")

        if not payment_id:
            _logger.info("Notificación de Mercado Pago sin data.id, ignorada")
            return request.make_response("", status=200)

        accounts = request.env["mercadopago.account"].sudo().search([("active", "=", True)])
        for account in accounts:
            if account.ingest_payment_id(str(payment_id)):
                break

        return request.make_response("", status=200)
