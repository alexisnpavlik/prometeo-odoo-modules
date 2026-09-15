# -*- coding: utf-8 -*-
"""Deja un solo número de contacto por cliente: el celular.

El teléfono fijo no lo usaba nadie para cobrar y tener dos campos hacía que el
número quedara en cualquiera de los dos. Lo que estaba cargado como fijo pasa al
celular cuando el celular está vacío.

Cuando el cliente tenía los dos y son distintos, se conserva el celular y el fijo se
anota en el historial: Odoo borra la columna del campo eliminado al terminar la
actualización, así que si no queda escrito acá, ese número se pierde.
"""
import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.mail import plaintext2html

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Copia el fijo al celular, o lo anota en el historial si ya había celular."""
    if not version:
        return
    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'cvi_customer' AND column_name = 'phone'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE cvi_customer
           SET mobile = phone
         WHERE btrim(coalesce(phone, '')) <> ''
           AND btrim(coalesce(mobile, '')) = ''
    """)
    moved = cr.rowcount
    cr.execute("""
        SELECT id, phone FROM cvi_customer
         WHERE btrim(coalesce(phone, '')) <> ''
           AND btrim(coalesce(mobile, '')) <> ''
           AND btrim(phone) <> btrim(mobile)
         ORDER BY id
    """)
    pending = cr.fetchall()
    if pending:
        env = api.Environment(cr, SUPERUSER_ID, {})
        customers = env["cvi.customer"]
        for customer_id, phone in pending:
            # _message_log y no message_post: deja la nota sin notificar a nadie, así no
            # depende de que el usuario que corre la migración tenga email cargado.
            customers.browse(customer_id)._message_log(
                body=plaintext2html(
                    "Teléfono fijo que estaba cargado antes de dejar solo el "
                    "celular: %s" % phone
                ),
            )
    if moved or pending:
        _logger.info(
            "Teléfonos: %s pasados a celular, %s anotados en el historial",
            moved, len(pending),
        )
