# -*- coding: utf-8 -*-
"""Migra validation_type: se elimina la contraseña; las credenciales pasan a ser de la caja."""

import logging

_logger = logging.getLogger(__name__)

VALIDATION_TYPE_MAP = {
    'password': 'pin',
    'pin_password': 'pin',
    'password_barcode': 'barcode',
    'pin_barcode': 'all',
}


def migrate(cr, version):
    """Convierte los valores de validation_type que dejan de existir."""
    for old, new in VALIDATION_TYPE_MAP.items():
        cr.execute("UPDATE pos_config SET validation_type = %s WHERE validation_type = %s", (new, old))
        if cr.rowcount:
            _logger.info("pos_special_approval_omax: validation_type %s -> %s en %s cajas", old, new, cr.rowcount)
