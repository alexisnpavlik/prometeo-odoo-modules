"""Helpers HTTP compartidos por los adaptadores."""
import requests

from . import LlmError


FRIENDLY = {
    400: "El proveedor rechazó el pedido (400): revisá que el modelo exista",
    401: "La clave de API no es válida (401)",
    402: "El proveedor no tiene crédito disponible (402): cargá saldo en su consola",
    403: "La clave no tiene permiso para este modelo (403)",
    404: "El modelo no existe en el proveedor (404)",
    429: "Se alcanzó el límite de uso del proveedor (429): probá en unos minutos",
}


def _clean(text, secret):
    """Recorta el cuerpo de error y borra la clave si apareciera."""
    text = (text or "")[:300]
    return text.replace(secret, "***") if secret else text


def request_json(method, url, secret, timeout, **kwargs):
    """Hace la llamada y devuelve el JSON; cualquier problema se convierte en LlmError."""
    try:
        call = requests.get if method == "GET" else requests.post
        resp = call(url, timeout=timeout, **kwargs)
    except requests.RequestException as e:
        raise LlmError(_clean("Error de conexión con el proveedor: %s" % e, secret))
    if resp.status_code != 200:
        hint = FRIENDLY.get(resp.status_code, "El proveedor respondió %s" % resp.status_code)
        raise LlmError(_clean("%s. Detalle: %s" % (hint, resp.text), secret), status=resp.status_code)
    try:
        return resp.json()
    except ValueError:
        raise LlmError(_clean("Respuesta no JSON del proveedor: %s" % resp.text, secret))
