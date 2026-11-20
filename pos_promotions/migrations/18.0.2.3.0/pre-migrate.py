# -*- coding: utf-8 -*-


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", [table])
    return bool(cr.fetchone()[0])


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
    # Las listas/sucursales permitidas en Ajustes ya no existen.
    cr.execute("""
        DELETE FROM ir_config_parameter
         WHERE key IN ('pos_promotions.allowed_pricelist_ids', 'pos_promotions.allowed_company_ids')
    """)
