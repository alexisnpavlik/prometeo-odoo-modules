# -*- coding: utf-8 -*-
"""Guarda el mueble de cada tarjeta antes de que product_id pase a ser calculado.

A partir de 18.0.2.0.0 una tarjeta puede tener varios muebles y la fuente de verdad
son las líneas. product_id, plan_id y quantity quedan como campos calculados desde la
primera línea: al actualizar, Odoo los recalcularía contra una lista de líneas vacía y
borraría el dato. Acá se copian a una tabla temporal que post-migrate consume.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'cvi_card' AND column_name = 'product_id'
    """)
    if not cr.fetchone():
        return
    cr.execute("DROP TABLE IF EXISTS cvi_card_line_migration")
    cr.execute("""
        CREATE TABLE cvi_card_line_migration AS
        SELECT id AS card_id, product_id, plan_id, quantity,
               installment_count, installment_amount, frequency
        FROM cvi_card
        WHERE product_id IS NOT NULL AND plan_id IS NOT NULL
    """)
    cr.execute("SELECT COUNT(*) FROM cvi_card_line_migration")
    _logger.info(
        "Migración de líneas: %s tarjetas con mueble guardadas", cr.fetchone()[0]
    )
