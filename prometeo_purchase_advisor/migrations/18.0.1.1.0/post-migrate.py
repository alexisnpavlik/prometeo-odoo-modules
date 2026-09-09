from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Actualiza los totales almacenados manteniendo el precio legado de compra."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env["prometeo.purchase.suggestion.line"].search([
        ("price_in_stock_uom", "=", False),
    ])
    lines._compute_subtotal()
    env.flush_all()
