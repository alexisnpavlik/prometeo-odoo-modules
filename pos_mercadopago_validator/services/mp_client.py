import logging
import time

import requests

_logger = logging.getLogger(__name__)

API_ROOT = "https://api.mercadopago.com"
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
MAX_ATTEMPTS = 3
BACKOFF_BASE = 0.5


class MercadoPagoError(Exception):
    """Error definitivo de la API. No se reintenta."""


class MercadoPagoAuthError(MercadoPagoError):
    """401/403: credenciales inválidas o sin permiso. Error de configuración."""


class MercadoPagoTransientError(Exception):
    """Error de red o 5xx. Reintentable."""


class MercadoPagoClient:
    """Cliente HTTP de la API de Mercado Pago.

    No conoce modelos de Odoo: recibe un token y devuelve diccionarios.
    """

    def __init__(self, access_token):
        self.access_token = access_token

    def _headers(self):
        """Arma los headers de autenticación."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def _call(self, method, path, params=None):
        """Ejecuta la llamada con reintentos y clasificación de errores."""
        url = API_ROOT + path
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = requests.request(
                    method, url,
                    headers=self._headers(),
                    params=params,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except requests.exceptions.RequestException as error:
                last_error = error
                _logger.warning("Mercado Pago inalcanzable (intento %s): %s", attempt + 1, error)
                time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue

            if response.status_code in (401, 403):
                raise MercadoPagoAuthError(
                    "Credenciales rechazadas por Mercado Pago (HTTP %s)" % response.status_code
                )
            if response.status_code >= 500:
                last_error = "HTTP %s" % response.status_code
                _logger.warning("Mercado Pago devolvió %s (intento %s)", response.status_code, attempt + 1)
                time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue
            if response.status_code >= 400:
                raise MercadoPagoError(
                    "Mercado Pago rechazó la consulta (HTTP %s)" % response.status_code
                )
            return response.json()

        raise MercadoPagoTransientError(
            "Mercado Pago no respondió tras %s intentos: %s" % (MAX_ATTEMPTS, last_error)
        )

    def get_me(self):
        """Devuelve los datos de la cuenta dueña del token."""
        return self._call("GET", "/users/me")

    def search_payments(self, begin_date, end_date, limit=50, offset=0):
        """Busca pagos acreditados en la ventana indicada.

        `begin_date` y `end_date` aceptan la sintaxis relativa de Mercado Pago
        (``NOW-5MINUTES``, ``NOW``), verificada contra la API el 2026-08-03.
        """
        return self._call("GET", "/v1/payments/search", params={
            "sort": "date_created",
            "criteria": "desc",
            "range": "date_created",
            "begin_date": begin_date,
            "end_date": end_date,
            "status": "approved",
            "limit": limit,
            "offset": offset,
        })

    def get_payment(self, payment_id):
        """Trae un pago puntual por id."""
        return self._call("GET", "/v1/payments/%s" % payment_id)
