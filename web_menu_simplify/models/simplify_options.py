# -*- coding: utf-8 -*-
"""Opciones de simplificación: qué oculta cada interruptor de Ajustes.

Cada opción se guarda en ir.config_parameter como "1"/"0" (no como booleano:
set_param(False) borra el parámetro y no se podría tener "activado por defecto").
Un parámetro ausente cuenta como activado.
"""

PARAM_PREFIX = "web_menu_simplify."

# opción -> menús que oculta (sus submenús también se ocultan).
# Los xmlids de módulos no instalados se ignoran.
MENU_OPTIONS = {
    # General
    "hide_discuss": ("mail.menu_root_discuss",),
    "hide_dashboards": ("spreadsheet_dashboard.spreadsheet_dashboard_menu_root",),
    "hide_link_tracker": ("utm.menu_link_tracker_root",),
    "hide_tests": ("base.menu_tests",),
    # Punto de venta
    "hide_pos_reports": ("point_of_sale.menu_point_rep",),
    "hide_pos_categories": ("point_of_sale.menu_products_pos_category",),
    "hide_pos_combos": ("point_of_sale.menu_product_combo",),
    "hide_pos_printers": ("point_of_sale.menu_pos_preparation_printer",),
    "hide_pos_note_models": ("point_of_sale.menu_pos_note_model",),
    # Facturación
    "hide_account_dashboard": ("account.menu_board_journal_1",),
    "hide_account_bank_cash": ("account_internal_transfer.menu_finance_bank_and_cash",),
    "hide_account_entries": ("account.menu_finance_entries",),
    "hide_account_reports": ("account.menu_finance_reports",),
    "hide_account_ledgers": ("account_ux.menu_customer_ledger", "account_ux.menu_vendor_ledger"),
    # Inventario
    "hide_stock_procurement": ("stock.menu_stock_procurement", "stock.menu_procurement_compute"),
    "hide_stock_lots": ("stock.menu_action_production_lot_form",),
    "hide_stock_packages": ("stock.menu_package",),
    "hide_stock_move_analysis": ("stock.stock_move_menu",),
    "hide_stock_valuation": ("stock_account.menu_valuation",),
    # Productos (en todas las apps)
    "hide_variants": (
        "stock.product_product_menu",
        "point_of_sale.pos_config_menu_action_product_product",
        "sale.menu_products",
        "purchase.product_product_menu",
    ),
    "hide_attributes": (
        "stock.menu_attribute_action",
        "point_of_sale.pos_menu_products_attribute_action",
        "sale.menu_product_attribute_action",
        "purchase.menu_product_attribute_action",
    ),
    "hide_pricelists": (
        "point_of_sale.pos_config_menu_action_product_pricelist",
        "sale.menu_product_pricelist_main",
        "purchase.menu_product_pricelist_action2_purchase",
    ),
}

# opción -> {tipo de vista: xpaths} de los elementos que oculta en las vistas
# de producto. Las xpaths de campos apuntan a su contenedor exacto para no
# tocar campos homónimos de subvistas.
VIEW_OPTIONS = {
    "hide_pricelists": {"form": ("//button[@name='open_pricelist_rules']",)},
    "hide_product_documents": {"form": ("//button[@name='action_open_documents']",)},
    "hide_reordering_rules": {
        "form": ("//button[@name='action_view_orderpoints']",),
        "list": ("//button[@name='action_view_orderpoints']",),
    },
    "hide_product_type_fields": {
        "form": (
            "//group[@name='group_general']/field[@name='type']",
            "//group[@name='group_general']/field[@name='invoice_policy']",
            "//group[@name='group_general']/label[@for='is_storable']",
            "//group[@name='group_general']/div[field[@name='is_storable']]",
            "//group[@name='group_general']/field[@name='product_tooltip']",
        ),
    },
    "hide_product_sale_flags": {
        "form": (
            "//div[@name='options']/span[field[@name='sale_ok']]",
            "//div[@name='options']/span[field[@name='purchase_ok']]",
            "//div[@name='options']/span[field[@name='available_in_pos']]",
        ),
    },
}

# Opciones sin menús ni vistas: las resuelve el frontend.
OTHER_OPTIONS = ("hide_systray",)

ALL_OPTIONS = tuple(dict.fromkeys((*MENU_OPTIONS, *VIEW_OPTIONS, *OTHER_OPTIONS)))


def is_option_active(env, key):
    """Indica si la opción está activada; sin parámetro guardado cuenta como activada."""
    return env["ir.config_parameter"].sudo().get_param(PARAM_PREFIX + key, "1") != "0"


def active_view_options(env):
    """Devuelve las opciones de vistas activadas (sirve como clave de caché de vistas)."""
    return tuple(key for key in VIEW_OPTIONS if is_option_active(env, key))


def hide_option_nodes(env, arch, view_type):
    """Oculta en la arquitectura de la vista los elementos de las opciones activadas."""
    attribute = "column_invisible" if view_type == "list" else "invisible"
    for key in active_view_options(env):
        for xpath in VIEW_OPTIONS[key].get(view_type, ()):
            for node in arch.xpath(xpath):
                node.set(attribute, "1")
