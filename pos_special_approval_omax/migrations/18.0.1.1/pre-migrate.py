# -*- coding: utf-8 -*-
"""
Migración a credencial por caja.

1. validation_type: se elimina la contraseña.
2. Copia a cada caja (pos.config) el código de barras / PIN que hoy usan sus
   usuarios autorizantes (manager_ids). Corre en pre-migrate porque el upgrade
   borra las columnas pos_barcode / pos_pin de res_users.

Regla por caja, ignorando administradores del sistema (base.group_system):
el código del usuario cuyo login empieza con 'encargado'; si no hay, el más repetido.
"""

import logging
from collections import Counter

_logger = logging.getLogger(__name__)

VALIDATION_TYPE_MAP = {
    'password': 'pin',
    'pin_password': 'pin',
    'password_barcode': 'barcode',
    'pin_barcode': 'all',
}


def _column_exists(cr, table, column):
    """True si la columna existe en la tabla."""
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    return bool(cr.fetchone())


def _pick_credential(candidates):
    """Elige la credencial de la caja: la del encargado, o la más repetida."""
    values = [(login, value) for login, value in candidates if value]
    if not values:
        return None, None
    for login, value in values:
        if (login or '').lower().startswith('encargado'):
            return value, login
    value, _count = Counter(v for _l, v in values).most_common(1)[0]
    source = next(login for login, v in values if v == value)
    return value, source


def _migrate_validation_type(cr):
    """Convierte los valores de validation_type que dejan de existir."""
    for old, new in VALIDATION_TYPE_MAP.items():
        cr.execute("UPDATE pos_config SET validation_type = %s WHERE validation_type = %s", (new, old))
        if cr.rowcount:
            _logger.info("pos_special_approval_omax: validation_type %s -> %s en %s cajas", old, new, cr.rowcount)


def _migrate_credentials(cr):
    """Copia a cada caja la credencial de sus usuarios autorizantes."""
    cr.execute("SELECT to_regclass('manager_validation_rel')")
    if not cr.fetchone()[0] or not _column_exists(cr, 'res_users', 'pos_barcode'):
        _logger.info("pos_special_approval_omax: sin credenciales por usuario para migrar")
        return

    has_pin = _column_exists(cr, 'res_users', 'pos_pin')
    cr.execute("ALTER TABLE pos_config ADD COLUMN IF NOT EXISTS approval_barcode varchar")
    cr.execute("ALTER TABLE pos_config ADD COLUMN IF NOT EXISTS approval_pin varchar")

    cr.execute("""
        SELECT r.config_id, u.login,
               NULLIF(TRIM(u.pos_barcode), ''),
               %s
          FROM manager_validation_rel r
          JOIN res_users u ON u.id = r.user_id
         WHERE u.id NOT IN (
                SELECT gu.uid
                  FROM res_groups_users_rel gu
                  JOIN ir_model_data d ON d.res_id = gu.gid
                 WHERE d.model = 'res.groups' AND d.module = 'base' AND d.name = 'group_system')
         ORDER BY r.config_id, u.id
    """ % ("NULLIF(TRIM(u.pos_pin), '')" if has_pin else "NULL"))

    by_config = {}
    for config_id, login, barcode, pin in cr.fetchall():
        by_config.setdefault(config_id, []).append((login, barcode, pin))

    for config_id, users in by_config.items():
        barcode, barcode_src = _pick_credential([(l, b) for l, b, _p in users])
        pin, pin_src = _pick_credential([(l, p) for l, _b, p in users])
        if pin and not pin.isdigit():
            pin, pin_src = None, None
        cr.execute("""
            UPDATE pos_config
               SET approval_barcode = COALESCE(approval_barcode, %s),
                   approval_pin = COALESCE(approval_pin, %s)
             WHERE id = %s
        """, (barcode, pin, config_id))
        _logger.info(
            "pos_special_approval_omax: caja %s -> código de %s, PIN de %s",
            config_id, barcode_src or '-', pin_src or '-',
        )


def _drop_users_view(cr):
    """Borra la vista vieja de res.users (pos_barcode/pos_pin) antes de que se quiten los campos."""
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'pos_special_approval_omax' AND name = 'base_form_res_users' AND model = 'ir.ui.view'
    """)
    row = cr.fetchone()
    if not row:
        return
    cr.execute("DELETE FROM ir_ui_view WHERE id = %s OR inherit_id = %s", (row[0], row[0]))
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'pos_special_approval_omax' AND name = 'base_form_res_users'
    """)
    _logger.info("pos_special_approval_omax: vista base_form_res_users eliminada")


def migrate(cr, version):
    """Punto de entrada de la migración 18.0.1.1."""
    _migrate_validation_type(cr)
    _migrate_credentials(cr)
    _drop_users_view(cr)
