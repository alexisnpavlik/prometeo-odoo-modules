def migrate(cr, version):
    """Conserva el significado de los precios guardados antes de esta versión."""
    cr.execute("""
        ALTER TABLE prometeo_purchase_suggestion_line
        ADD COLUMN IF NOT EXISTS price_in_stock_uom boolean
    """)
    cr.execute("""
        UPDATE prometeo_purchase_suggestion_line
           SET price_in_stock_uom = false
         WHERE price_in_stock_uom IS NULL
    """)
