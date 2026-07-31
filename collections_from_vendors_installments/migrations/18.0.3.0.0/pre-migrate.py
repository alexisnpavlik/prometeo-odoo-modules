# -*- coding: utf-8 -*-
"""Convierte los contactos usados como clientes en registros de cvi.customer.

Desde 18.0.3.0.0 el cliente deja de ser un res.partner y pasa a ser un modelo propio
identificado por DNI. Esta migración corre ANTES de que Odoo cree la columna
customer_id, así que crea la tabla e inserta los clientes por SQL, y deja el mapeo
partner -> customer en una tabla temporal que post-migrate usa para completar las
tarjetas.

Los contactos sin DNI reciben un marcador SIN-DNI-<id>. No se inventa un documento ni
se fusionan homónimos: fusionar dos personas distintas por error es mucho peor que
dejar el dato pendiente y a la vista.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'cvi_card' AND column_name = 'partner_id'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'cvi_dni'
    """)
    has_dni = bool(cr.fetchone())
    dni_expr = "NULLIF(REGEXP_REPLACE(COALESCE(p.cvi_dni, ''), '[^0-9A-Za-z]', '', 'g'), '')" if has_dni else "NULL"

    cr.execute("""
        CREATE TABLE IF NOT EXISTS cvi_customer (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            dni VARCHAR NOT NULL,
            company_id INTEGER NOT NULL,
            active BOOLEAN DEFAULT TRUE,
            phone VARCHAR, mobile VARCHAR, street VARCHAR, city VARCHAR, zip VARCHAR,
            note TEXT,
            problematic BOOLEAN DEFAULT FALSE,
            problematic_reason VARCHAR,
            problematic_date DATE,
            problematic_user_id INTEGER,
            create_uid INTEGER, create_date TIMESTAMP,
            write_uid INTEGER, write_date TIMESTAMP
        )
    """)
    cr.execute("DROP TABLE IF EXISTS cvi_customer_migration")
    cr.execute(f"""
        CREATE TABLE cvi_customer_migration AS
        SELECT DISTINCT p.id AS partner_id, c.company_id,
               COALESCE({dni_expr}, 'SIN-DNI-' || p.id) AS dni
        FROM cvi_card c
        JOIN res_partner p ON p.id = c.partner_id
    """)
    problematic_cols = ""
    problematic_vals = ""
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'cvi_problematic'
    """)
    if cr.fetchone():
        problematic_cols = ", problematic, problematic_reason, problematic_date, problematic_user_id"
        problematic_vals = (", COALESCE(p.cvi_problematic, FALSE), p.cvi_problematic_reason,"
                            " p.cvi_problematic_date, p.cvi_problematic_user_id")

    cr.execute(f"""
        INSERT INTO cvi_customer (
            name, dni, company_id, active, phone, mobile, street, city, zip,
            create_uid, create_date, write_uid, write_date{problematic_cols}
        )
        SELECT COALESCE(p.complete_name, p.name, 'Cliente ' || p.id), m.dni, m.company_id,
               TRUE, p.phone, p.mobile, p.street, p.city, p.zip,
               1, NOW() AT TIME ZONE 'UTC', 1, NOW() AT TIME ZONE 'UTC'{problematic_vals}
        FROM cvi_customer_migration m
        JOIN res_partner p ON p.id = m.partner_id
    """)
    created = cr.rowcount

    cr.execute("""
        ALTER TABLE cvi_customer_migration ADD COLUMN customer_id INTEGER
    """)
    cr.execute("""
        UPDATE cvi_customer_migration m
        SET customer_id = cu.id
        FROM cvi_customer cu
        WHERE cu.dni = m.dni AND cu.company_id = m.company_id
    """)
    cr.execute("SELECT COUNT(*) FROM cvi_customer_migration WHERE dni LIKE 'SIN-DNI-%'")
    missing = cr.fetchone()[0]
    _logger.info(
        "Migración de clientes: %s creados desde contactos, %s sin DNI cargado",
        created, missing,
    )
