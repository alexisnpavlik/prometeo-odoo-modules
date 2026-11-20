# -*- coding: utf-8 -*-


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", [table])
    return bool(cr.fetchone()[0])


def _column_exists(cr, table, column):
    cr.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        [table, column],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """De listas a sucursales (bases en 18.0.2.1/2.2): cada lista pasa a la empresa dueña;
    una lista sin empresa, a todas. Se guarda en una tabla temporal para el post-migrate."""
    if _table_exists(cr, "pos_promotion_pricelist_rel"):
        cr.execute("""
            CREATE TABLE pos_promotion_company_mig AS
            SELECT DISTINCT r.product_tmpl_id, COALESCE(pl.company_id, c.id) AS company_id
              FROM pos_promotion_pricelist_rel r
              JOIN product_pricelist pl ON pl.id = r.pricelist_id
              JOIN res_company c ON pl.company_id IS NULL OR c.id = pl.company_id
        """)
    if _table_exists(cr, "pos_promotion_price") and _column_exists(cr, "pos_promotion_price", "pricelist_id"):
        cr.execute("ALTER TABLE pos_promotion_price ALTER COLUMN pricelist_id DROP NOT NULL")
        cr.execute("ALTER TABLE pos_promotion_price ADD COLUMN IF NOT EXISTS company_id integer")
        cr.execute("""
            UPDATE pos_promotion_price p SET company_id = pl.company_id
              FROM product_pricelist pl WHERE pl.id = p.pricelist_id
        """)
        # Sin empresa no hay a qué sucursal asignarlo; con dos listas de la misma empresa, queda uno.
        cr.execute("DELETE FROM pos_promotion_price WHERE company_id IS NULL")
        cr.execute("""
            DELETE FROM pos_promotion_price p USING pos_promotion_price q
             WHERE p.pack_tmpl_id = q.pack_tmpl_id AND p.company_id = q.company_id AND p.id < q.id
        """)
    cr.execute("""
        SELECT value FROM ir_config_parameter WHERE key = 'pos_promotions.allowed_pricelist_ids'
    """)
    row = cr.fetchone()
    if row and row[0]:
        ids = [int(v) for v in row[0].split(",") if v.strip().isdigit()]
        cr.execute(
            "SELECT DISTINCT company_id FROM product_pricelist WHERE id = ANY(%s) AND company_id IS NOT NULL",
            [ids],
        )
        companies = ",".join(str(r[0]) for r in cr.fetchall())
        cr.execute("""
            INSERT INTO ir_config_parameter (key, value, create_date, write_date)
            VALUES ('pos_promotions.allowed_company_ids', %s, now(), now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [companies])
    cr.execute("DELETE FROM ir_config_parameter WHERE key = 'pos_promotions.allowed_pricelist_ids'")
