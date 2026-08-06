# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
"""Helpers compartidos por los tres modelos que participan del espejo intercompany."""

import logging

from odoo import _

_logger = logging.getLogger(__name__)

# Marca una escritura como "ya propagada": el override de la contraparte la ve
# y sale temprano, cortando el eco en un solo salto.
SYNC_CONTEXT_KEY = "skip_intercompany_sync"


def is_propagation(env):
    """Verdadero si la escritura en curso ya viene propagada desde la contraparte."""
    return bool(env.context.get(SYNC_CONTEXT_KEY))


def as_propagation(records):
    """Devuelve el recordset listo para recibir la propagación: sudo y con el flag."""
    return records.sudo().with_context(**{SYNC_CONTEXT_KEY: True})


def get_counterpart(record, field_name):
    """Resuelve la contraparte en cualquiera de los dos sentidos del vínculo.

    El campo `field_name` solo lo llena el registro espejo apuntando al origen,
    así que desde el origen hay que buscarlo al revés.
    """
    record.ensure_one()
    counterpart = record[field_name]
    if counterpart:
        return counterpart
    if not record.id:
        return record.browse()
    return record.sudo().search([(field_name, "=", record.id)], limit=1)


def map_lot(lot, company):
    """Devuelve el lote equivalente en `company`, creándolo si no existe.

    `stock.lot` es por compañía: el lote de la entrega no sirve en la recepción.
    El equivalente se identifica por nombre y producto.
    """
    if not lot:
        return False
    if lot.company_id == company:
        return lot
    lot_model = lot.sudo().with_company(company)
    existing = lot_model.search(
        [
            ("name", "=", lot.name),
            ("product_id", "=", lot.product_id.id),
            ("company_id", "=", company.id),
        ],
        limit=1,
    )
    if existing:
        return existing
    _logger.info(
        "Intercompany: creando lote %s del producto %s en la compañía %s",
        lot.name,
        lot.product_id.display_name,
        company.name,
    )
    return lot_model.create(
        {
            "name": lot.name,
            "product_id": lot.product_id.id,
            "company_id": company.id,
        }
    )


def post_sync_note(picking, body, source_picking=None):
    """Postea la nota de auditoría en el chatter del picking.

    Cuando el cambio llega propagado, la nota nombra el picking de origen y el
    usuario que lo originó, que puede ser de la otra compañía.
    """
    if source_picking:
        body = _(
            "%(body)s — propagado desde %(origin)s (%(company)s) por %(user)s",
            body=body,
            origin=source_picking.name,
            company=source_picking.company_id.name,
            user=picking.env.user.name,
        )
    picking.sudo().message_post(body=body)
