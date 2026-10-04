from odoo import fields, models

# Lista por defecto que Odoo crea en cada empresa; no se gestiona desde la ficha.
EXCLUDED_PRICELIST_NAME = "Predeterminado"

# Sin allowed_company_ids Odoo usa todas las empresas del usuario (env.companies),
# así la tabla muestra las listas de cada empresa aunque haya una sola tildada.
ALL_USER_COMPANIES_CONTEXT = {"allowed_company_ids": False}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    pricelist_line_ids = fields.One2many(
        "product.pricelist.item",
        "product_tmpl_id",
        string="Listas de precios",
        domain=[
            ("applied_on", "=", "1_product"),
            ("compute_price", "=", "fixed"),
            ("pricelist_id.name", "!=", EXCLUDED_PRICELIST_NAME),
        ],
        context={
            "default_applied_on": "1_product",
            "default_compute_price": "fixed",
            **ALL_USER_COMPANIES_CONTEXT,
        },
        help="Reglas de precio fijo de cada lista para este producto. Son las "
             "mismas reglas que se ven desde la lista de precios.",
    )
