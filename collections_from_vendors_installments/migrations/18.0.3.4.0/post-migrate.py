# -*- coding: utf-8 -*-
"""Pasa al historial del cliente el texto que estaba en el campo Observaciones.

Hasta 18.0.3.3.0 la ficha tenía un campo libre que se pisaba sin dejar rastro de
quién lo escribió ni cuándo. Ahora las notas se registran en el chatter, así que lo
que había se postea como nota registrada para no perderlo.

Odoo borra la columna del campo eliminado al terminar la actualización, así que el
chatter queda como único lugar donde vive ese texto: si este script no lo postea, se
pierde. Por eso no filtra nada y corre sobre todos los clientes.
"""
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.mail import plaintext2html

_logger = logging.getLogger(__name__)

HEADER = "Observaciones cargadas antes de pasar las notas al historial:"


def migrate(cr, version):
    """Postea una nota por cliente que tenga texto en la columna vieja."""
    if not version:
        return
    cr.execute("""
        SELECT id, note FROM cvi_customer
         WHERE note IS NOT NULL AND btrim(note) <> ''
         ORDER BY id
    """)
    rows = cr.fetchall()
    if not rows:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    customers = env["cvi.customer"]
    for customer_id, note in rows:
        customers.browse(customer_id).message_post(
            body=plaintext2html("%s\n\n%s" % (HEADER, note)),
            subtype_xmlid="mail.mt_note",
        )
    _logger.info("Observaciones pasadas al historial: %s clientes", len(rows))
