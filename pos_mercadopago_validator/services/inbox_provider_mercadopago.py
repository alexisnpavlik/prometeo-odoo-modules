import logging

from .inbox_provider import InboxProvider

_logger = logging.getLogger(__name__)

SUB_UNIT_QR = "qr"
SUB_UNIT_ALIAS = "money_inflows"
INGESTABLE_SUB_UNITS = (SUB_UNIT_QR, SUB_UNIT_ALIAS)


class MercadoPagoInboxProvider(InboxProvider):
    """Normaliza los pagos de Mercado Pago hacia el modelo de bandeja.

    Las reglas de esta clase salen de la verificación empírica del 2026-08-03
    documentada en el spec; no inferirlas de la documentación de Mercado Pago.
    """

    def __init__(self, client, mp_user_id):
        """Guarda el cliente HTTP y el id del comercio dueño de la cuenta."""
        self.client = client
        self.mp_user_id = str(mp_user_id)

    # -- ingesta --------------------------------------------------------

    def fetch_payments(self, window_start, window_end):
        """Trae los pagos acreditados de la ventana, paginando."""
        results, offset = [], 0
        while True:
            page = self.client.search_payments(window_start, window_end, limit=50, offset=offset)
            batch = page.get("results", [])
            results.extend(batch)
            paging = page.get("paging", {})
            offset += len(batch)
            if not batch or offset >= paging.get("total", 0):
                break
        return results

    def get_payment(self, payment_id):
        """Trae un pago puntual con credenciales propias."""
        return self.client.get_payment(payment_id)

    def parse_notification(self, payload):
        """Extrae únicamente el identificador del pago. Todo lo demás se descarta."""
        data = (payload or {}).get("data") or {}
        return data.get("id")

    # -- clasificación --------------------------------------------------

    def _business_info(self, raw):
        """Devuelve el business_info del pago, siempre un dict."""
        poi = raw.get("point_of_interaction") or {}
        return poi.get("business_info") or {}

    def is_ingestable(self, raw):
        """Filtro de §6.1: sólo cobros acreditados propios, por QR o alias."""
        if raw.get("status") != "approved" or raw.get("status_detail") != "accredited":
            return False
        if str(raw.get("collector_id") or "") != self.mp_user_id:
            return False
        return self._business_info(raw).get("sub_unit") in INGESTABLE_SUB_UNITS

    # -- normalización --------------------------------------------------

    def normalize(self, raw):
        """Convierte un pago crudo en campos del modelo de bandeja.

        La identificación del pagador sólo se conserva en el canal QR: en el
        canal alias Mercado Pago devuelve los datos del receptor (§2.3).
        """
        poi = raw.get("point_of_interaction") or {}
        is_qr = self._business_info(raw).get("sub_unit") == SUB_UNIT_QR
        payer = raw.get("payer") or {}
        bank_payer = (
            ((poi.get("transaction_data") or {}).get("bank_info") or {}).get("payer") or {}
        )

        row = {
            "mp_payment_id": str(raw["id"]),
            "amount": raw["transaction_amount"],
            "date_approved": self._parse_datetime(raw.get("date_approved")),
            "source": "qr" if is_qr else "alias",
            "mp_pos_id": str(raw["pos_id"]) if is_qr and raw.get("pos_id") else False,
            "payer_bank_name": bank_payer.get("long_name") or False,
            "payment_method_detail": raw.get("payment_method_id"),
            "raw_status": raw.get("status_detail"),
            "payer_vat": False,
            "payer_email": False,
            "mp_payer_id": False,
        }

        if is_qr:
            payer_id = str(payer.get("id") or "")
            # Red de seguridad: si el payer es el propio collector, el dato es
            # del receptor y no se guarda.
            if payer_id and payer_id != self.mp_user_id:
                row["mp_payer_id"] = payer_id
                row["payer_email"] = payer.get("email") or False
                row["payer_vat"] = (payer.get("identification") or {}).get("number") or False

        return row

    def _parse_datetime(self, value):
        """Convierte el ISO-8601 con offset de MP a naive UTC para Odoo."""
        from datetime import datetime

        if not value:
            return False
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            from datetime import timezone

            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
