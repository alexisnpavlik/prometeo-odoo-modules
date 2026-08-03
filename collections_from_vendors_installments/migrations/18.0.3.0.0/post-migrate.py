# -*- coding: utf-8 -*-
"""Apunta las tarjetas al cliente propio creado en pre-migrate."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'cvi_customer_migration'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        UPDATE cvi_card c
        SET customer_id = m.customer_id
        FROM cvi_customer_migration m
        WHERE m.partner_id = c.partner_id AND m.customer_id IS NOT NULL
    """)
    updated = cr.rowcount
    # Los related almacenados de cuota y cobro se recalculan solos en la próxima
    # actualización, pero se completan acá para no dejar la base a medias entre medio.
    for table in ("cvi_installment", "cvi_payment"):
        cr.execute(f"""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = '{table}' AND column_name = 'customer_id'
        """)
        if cr.fetchone():
            cr.execute(f"""
                UPDATE {table} t SET customer_id = c.customer_id
                FROM cvi_card c WHERE c.id = t.card_id
            """)
    cr.execute("DROP TABLE cvi_customer_migration")
    _logger.info("Migración de clientes: %s tarjetas reapuntadas", updated)
