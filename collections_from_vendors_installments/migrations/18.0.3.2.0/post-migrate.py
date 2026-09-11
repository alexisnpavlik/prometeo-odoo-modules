# -*- coding: utf-8 -*-
"""Mueve a la ficha del cliente las fotos de DNI que estaban cargadas en las ventas.

Hasta 18.0.3.1.3 el documento se fotografiaba en cada tarjeta (cvi.card.photo_dni).
Ahora vive en el cliente, con frente y dorso, porque el DNI es de la persona y no de
cada compra. Los campos Image se guardan como adjuntos y no como columna, así que
mover la foto es repuntar el adjunto: no hay dato que copiar.

De cada cliente se conserva la foto de su venta más reciente como frente. Las de
ventas anteriores son el mismo documento fotografiado otra vez, así que se descartan
en vez de quedar como adjuntos huérfanos de un campo que ya no existe.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Repunta un adjunto por cliente y limpia los que quedan sin dueño."""
    if not version:
        return
    cr.execute("""
        SELECT a.id, c.customer_id
          FROM ir_attachment a
          JOIN cvi_card c ON c.id = a.res_id
         WHERE a.res_model = 'cvi.card'
           AND a.res_field = 'photo_dni'
           AND c.customer_id IS NOT NULL
         ORDER BY c.customer_id, c.date_sale DESC, c.id DESC
    """)
    candidates = cr.fetchall()
    # La ficha manda: si el cliente ya tiene el frente cargado, lo de las ventas es
    # una copia del mismo documento y no se pisa.
    cr.execute("""
        SELECT res_id FROM ir_attachment
         WHERE res_model = 'cvi.customer' AND res_field = 'photo_dni_front'
    """)
    taken = {row[0] for row in cr.fetchall()}
    moved = 0
    for attachment_id, customer_id in candidates:
        if customer_id in taken:
            continue
        cr.execute("""
            UPDATE ir_attachment
               SET res_model = 'cvi.customer',
                   res_id = %s,
                   res_field = 'photo_dni_front'
             WHERE id = %s
        """, (customer_id, attachment_id))
        taken.add(customer_id)
        moved += 1

    env = api.Environment(cr, SUPERUSER_ID, {})
    leftovers = env["ir.attachment"].search([
        ("res_model", "=", "cvi.card"),
        ("res_field", "=", "photo_dni"),
    ])
    discarded = len(leftovers)
    if discarded:
        leftovers.unlink()
    if moved or discarded:
        _logger.info(
            "Fotos de DNI movidas a la ficha del cliente: %s; duplicados descartados: %s",
            moved, discarded,
        )
