##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
"""Traduce fallas de red o del servidor de AFIP a un mensaje entendible.

Los webservices de AFIP se caen de muchas formas distintas (SoapFault, timeout
de lectura, conexión reseteada, XML truncado) y cada capa de la pila las
envuelve en un tipo de excepción propio, así que capturar por tipo no alcanza.
El criterio es el mismo que ya usaba ``afipws_connection.connect()``: matching
sobre ``repr(error)``, que incluye tanto el nombre de la clase como el mensaje.

Importante: esto identifica *"AFIP no contestó"*, no *"AFIP rechazó el
comprobante"*. Un rechazo trae código y motivo en ``ws.Obs`` / ``ws.ErrMsg`` y
se le muestra al usuario tal cual, porque el problema está en la factura y
reintentar no lo va a resolver.
"""

from odoo import _

# Fragmentos que aparecen en repr(error) cuando el problema es la conexión con
# AFIP y no el comprobante que se está enviando. El matching es case-insensitive.
AFIP_UNREACHABLE_HINTS = (
    "soapfault",
    "timed out",
    "timeout",
    "expaterror",
    "mismatched tag",
    "conexión reinicializada",
    "conexion reinicializada",
    "sslhandshakeerror",
    "sslerror",
    "connection refused",
    "connection reset",
    "connectionerror",
    "remotedisconnected",
    "badstatusline",
    "name or service not known",
    "temporary failure in name resolution",
    "no route to host",
    "unreachable",
    "urlerror",
    "gaierror",
    "errno 104",
    "errno 110",
    "errno 111",
    "errno -2",
)


def is_afip_unreachable(error):
    """Indica si ``error`` viene de que AFIP no contesta, no de un rechazo."""
    text = repr(error).lower()
    return any(hint in text for hint in AFIP_UNREACHABLE_HINTS)


def afip_connection_message():
    """Mensaje único que ve el usuario cuando AFIP no responde."""
    return _(
        "El servidor de AFIP no responde.\n\n"
        "La factura electrónica no se pudo autorizar. Reintentá en unos minutos."
    )
