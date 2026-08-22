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

import socket
import ssl

from odoo import _

# Excepciones de red de la biblioteca estándar. ConnectionError cubre rechazada,
# reseteada y abortada; TimeoutError cubre socket.timeout.
NETWORK_EXCEPTIONS = (ConnectionError, TimeoutError, socket.gaierror, ssl.SSLError)

# Módulos de la pila de red que usa pyafipws. Cualquier excepción definida ahí
# es un problema de transporte, no del comprobante. Se compara contra la primera
# parte de __module__ ("pysimplesoap.client" -> "pysimplesoap").
NETWORK_MODULES = frozenset({"httplib2", "pysimplesoap", "socket", "ssl", "http", "urllib"})

# Respaldo por texto, para errores que la pila envuelve en tipos genéricos: por
# ejemplo pyafipws levanta ValueError("The read operation timed out").
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


def describe_error(error):
    """``repr()`` seguro: describe la excepción sin levantar nunca.

    No es defensivo de más: ``pysimplesoap.client.SoapFault`` —el tipo que tira
    AFIP cuando rechaza el request a nivel SOAP— tiene un ``__repr__`` que
    referencia ``self.detail``, atributo que su ``__init__`` nunca define. O sea
    que ``repr()`` sobre un SoapFault levanta AttributeError y se lleva puesto
    al que lo estaba manejando.

    Siempre incluye el nombre de la clase, que es lo que permite reconocer el
    error aun cuando ``repr()`` y ``str()`` fallen los dos.
    """
    name = type(error).__name__
    for render in (repr, str):
        try:
            text = render(error)
        except Exception:  # noqa: BLE001 - describir un error no puede fallar
            continue
        if text:
            return text if name in text else "%s: %s" % (name, text)
    return name


def is_afip_unreachable(error):
    """Indica si ``error`` viene de que AFIP no contesta, no de un rechazo.

    Se mira primero el tipo y el módulo de la excepción, que es lo estable, y
    recién después el texto. Al revés se escapan cosas como
    ``httplib2.ServerNotFoundError``, cuyo nombre no contiene ninguna palabra
    obvia de red.
    """
    if isinstance(error, NETWORK_EXCEPTIONS):
        return True
    module = (getattr(type(error), "__module__", "") or "").split(".")[0]
    if module in NETWORK_MODULES:
        return True
    text = describe_error(error).lower()
    return any(hint in text for hint in AFIP_UNREACHABLE_HINTS)


def afip_connection_message():
    """Mensaje único que ve el usuario cuando AFIP no responde."""
    return _(
        "El servidor de AFIP no responde.\n\n"
        "La factura electrónica no se pudo autorizar. Reintentá en unos minutos."
    )
