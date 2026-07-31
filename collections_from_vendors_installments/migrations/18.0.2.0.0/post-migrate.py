# -*- coding: utf-8 -*-
"""Crea una línea por cada tarjeta que existía cuando la venta era de un solo mueble.

Se hace por SQL y no por ORM porque cvi.card.line bloquea altas en tarjetas ya
confirmadas (RN-05), y acá justamente hay que poblar tarjetas confirmadas y hasta
finalizadas. Los importes se copian tal cual estaban: recalcularlos desde el plan
cambiaría el precio de ventas ya cerradas si el plan se editó desde entonces.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'cvi_card_line_migration'
    """)
    if not cr.fetchone():
        return
    cr.execute("""
        INSERT INTO cvi_card_line (
            card_id, sequence, product_id, plan_id, quantity,
            installment_count, installment_amount, frequency,
            amount_per_installment, amount_subtotal,
            company_id, create_uid, create_date, write_uid, write_date
        )
        SELECT m.card_id, 10, m.product_id, m.plan_id, COALESCE(m.quantity, 1.0),
               m.installment_count, m.installment_amount, m.frequency,
               m.installment_amount * COALESCE(m.quantity, 1.0),
               m.installment_amount * COALESCE(m.quantity, 1.0) * m.installment_count,
               c.company_id, 1, NOW() AT TIME ZONE 'UTC', 1, NOW() AT TIME ZONE 'UTC'
        FROM cvi_card_line_migration m
        JOIN cvi_card c ON c.id = m.card_id
        WHERE NOT EXISTS (
            SELECT 1 FROM cvi_card_line l WHERE l.card_id = m.card_id
        )
    """)
    created = cr.rowcount
    # Devolver los valores a la cabecera: los campos son calculados y almacenados, y
    # el recálculo de la actualización ya corrió contra una tarjeta sin líneas.
    cr.execute("""
        UPDATE cvi_card c
        SET product_id = m.product_id,
            plan_id = m.plan_id,
            quantity = COALESCE(m.quantity, 1.0),
            line_count = 1
        FROM cvi_card_line_migration m
        WHERE m.card_id = c.id
    """)
    cr.execute("DROP TABLE cvi_card_line_migration")
    _logger.info("Migración de líneas: %s líneas creadas desde tarjetas viejas", created)
