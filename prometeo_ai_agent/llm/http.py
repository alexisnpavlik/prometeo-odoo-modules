"""Helpers HTTP compartidos por los adaptadores."""
import requests

from . import LlmError


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
        raise LlmError(_clean("El proveedor respondió %s: %s" % (resp.status_code, resp.text), secret),
                       status=resp.status_code)
    try:
        return resp.json()
    except ValueError:
        raise LlmError(_clean("Respuesta no JSON del proveedor: %s" % resp.text, secret))
