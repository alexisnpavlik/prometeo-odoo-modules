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
    "hide_sales": ("sale.sale_menu_root",),
    # Compras
    "purchase_simple": ("purchase.menu_procurement_management",),
    # Punto de venta
    "hide_pos_reports": ("point_of_sale.menu_point_rep",),
    "hide_pos_categories": ("point_of_sale.menu_products_pos_category",),
    "hide_pos_combos": ("point_of_sale.menu_product_combo",),
    "hide_pos_printers": ("point_of_sale.menu_pos_preparation_printer",),
    "hide_pos_note_models": ("point_of_sale.menu_pos_note_model",),
    # Facturación
    "hide_account": ("account.menu_finance",),
    "hide_account_dashboard": ("account.menu_board_journal_1",),
    "hide_account_bank_cash": ("account_internal_transfer.menu_finance_bank_and_cash",),
    "hide_account_entries": ("account.menu_finance_entries",),
    "hide_account_reports": ("account.menu_finance_reports",),
    "hide_account_ledgers": ("account_ux.menu_customer_ledger", "account_ux.menu_vendor_ledger"),
    # Inventario
    "hide_stock_overview": ("stock.stock_picking_type_menu",),
    "hide_stock_operations": ("stock.menu_stock_warehouse_mgmt",),
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

# opción -> menús propios que solo existen con la opción activa (se ocultan si está apagada).
MENU_OPTIONS_WHEN_OFF = {
    "pos_invoices_menu": ("web_menu_simplify.menu_pos_customer_invoices",),
    "stock_categories_menu": ("web_menu_simplify.menu_stock_product_categories",),
    "purchase_simple": (
        "web_menu_simplify.menu_purchase_orders_direct",
        "web_menu_simplify.menu_purchase_vendors_direct",
    ),
}

# Modelos a los que aplican las opciones de VIEW_OPTIONS sin clave "models".
PRODUCT_MODELS = ("product.template", "product.product")

# opción -> {tipo de vista: xpaths} de los elementos que oculta. "models" limita
# la opción a esos modelos (por defecto, las vistas de producto). Un item puede ser
# (xpath, atributo) para forzar el atributo (p. ej. column_invisible) o
# (xpath, atributo, valor) para reescribir una condición; (xpath, "remove") quita
# el nodo cuando el cliente ignora invisible. Las xpaths de
# campos apuntan a su contenedor exacto para no tocar campos homónimos de subvistas.
VIEW_OPTIONS = {
    "hide_purchase_order_fields": {
        "models": ("purchase.order",),
        "form": (
            "//sheet/group/group/field[@name='partner_ref']",
            "//sheet/group/group/field[@name='currency_id']",
            "//sheet/group/group/label[@for='date_planned']",
            "//sheet/group/group/div[@name='date_planned_div']",
            "//sheet/group/group/field[@name='date_order']",
            "//page[@name='purchase_delivery_invoice']",
            "//sheet/group/group/label[@for='receipt_reminder_email']",
            "//sheet/group/group/div[@name='reminder']",
            # El renderer de la lista ignora invisible en <control>: se quitan los nodos.
            ("//field[@name='order_line']/list/control/create[@name='add_section_control']", "remove"),
            ("//field[@name='order_line']/list/control/create[@name='add_note_control']", "remove"),
            ("//field[@name='order_line']/list/control/button[@name='action_add_from_catalog']", "remove"),
        ),
    },
    # Encabezado sin botones redundantes: en borrador solo Confirmar e ingresar; ya
    # confirmada, Devolver, Imprimir y (si falta) Recibir productos.
    "purchase_confirmed_only_return": {
        "models": ("purchase.order",),
        "form": (
            # Cancelar se oculta siempre: en borrador hace lo mismo que Descartar.
            "//header/button[@name='button_cancel']",
            "//header/button[@name='button_done']",
            "//header/button[@name='button_unlock']",
            "//header/button[@name='confirm_reminder_mail']",
            "//div[@name='button_box']/button[@name='action_view_picking']",
        ),
    },
    # Sin etapas de cotización: título "Orden de compra" siempre y sin barra de etapas.
    "purchase_order_no_rfq": {
        "models": ("purchase.order",),
        "form": (
            "//header/field[@name='state']",
            "//div[contains(@class, 'oe_title')]//span[@invisible=\"state not in ('draft', 'sent')\"]",
            ("//div[contains(@class, 'oe_title')]//span[@invisible=\"state in ('draft', 'sent')\"]", "invisible", "0"),
        ),
    },
    # Ficha de contacto: rutas absolutas para no tocar el subformulario de contactos hijos.
    "partner_form_simple": {
        "models": ("res.partner",),
        "form": (
            "/form/sheet/group/group/field[@name='function']",
            "/form/sheet/group/group/field[@name='website']",
            "/form/sheet/group/group/field[@name='title']",
            "/form/sheet/group/group/field[@name='lang']",
            "/form/sheet/group/group/field[@name='category_id']",
            "/form/sheet/notebook/page[@name='contact_addresses']",
            "/form/sheet/notebook/page[@name='sales_purchases']",
            "/form/sheet/notebook/page[@name='accounting']",
            "/form/sheet/notebook/page[@name='accounting_disabled']",
            "/form/sheet/notebook/page[@name='internal_notes']",
            "/form/sheet/div[@name='button_box']/button[@name='action_view_sale_order']",
            "/form/sheet/div[@name='button_box']/button[@name='action_view_stock_lots']",
            "/form/sheet/div[@name='button_box']/button[@invisible='payment_token_count == 0']",
        ),
    },
    "hide_purchase_order_invoice": {
        "models": ("purchase.order",),
        "form": ("//header/button[@name='action_create_invoice']",),
    },
    "hide_purchase_order_taxes": {
        "models": ("purchase.order",),
        # Columna de una lista embebida: necesita column_invisible aunque la vista sea form.
        "form": (("//field[@name='order_line']/list/field[@name='taxes_id']", "column_invisible"),),
    },
    # Con la opción activa, "Confirmar orden" se reemplaza por "Confirmar e ingresar".
    "purchase_confirm_receive": {
        "models": ("purchase.order",),
        "form": ("//header/button[@name='button_confirm']",),
    },
    "hide_purchase_order_send_print": {
        "models": ("purchase.order",),
        "form": (
            "//header/button[@name='action_rfq_send']",
            "//header/button[@name='print_quotation']",
        ),
    },
    "hide_pricelists": {"form": ("//button[@name='open_pricelist_rules']",)},
    "hide_product_documents": {"form": ("//button[@name='action_open_documents']",)},
    "hide_product_forecast": {
        "form": (
            "//div[@name='button_box']//button[@name='action_product_tmpl_forecast_report']",
            "//div[@name='button_box']//button[@name='action_product_forecast_report']",
        ),
    },
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
    "hide_update_quantity": {
        "form": ("//header/button[@name='action_update_quantity_on_hand']",),
    },
    "hide_sale_taxes": {
        "form": ("//label[@for='taxes_id']", "//div[@name='taxes_div']"),
    },
    "hide_purchase_taxes": {
        "form": ("//page[@name='general_information']//field[@name='supplier_taxes_id']",),
    },
    # Sin xpaths: lo resuelve comfort_product_form (está acá para la clave de caché).
    "product_form_comfort": {},
    "hide_product_sale_flags": {
        "form": (
            "//div[@name='options']/span[field[@name='sale_ok']]",
            "//div[@name='options']/span[field[@name='purchase_ok']]",
            "//div[@name='options']/span[field[@name='available_in_pos']]",
        ),
    },
}

# opción -> {app: acción con la que abre} (la app abre ahí en vez de en su
# primer submenú).
APP_START_OPTIONS = {
    "inventory_open_products": {"stock.menu_stock_root": "stock.product_template_action_product"},
}

# Opciones sin menús ni vistas: las resuelve el frontend.
OTHER_OPTIONS = (
    "hide_systray",
    "flatten_single_menus",
    "pos_first",
    "replenish_immediate",
    "replenish_buy_locked",
    "replenish_vendor_partner",
    "purchase_return_button",
)

ALL_OPTIONS = tuple(dict.fromkeys((*MENU_OPTIONS, *MENU_OPTIONS_WHEN_OFF, *VIEW_OPTIONS, *APP_START_OPTIONS, *OTHER_OPTIONS)))


def is_option_active(env, key):
    """Indica si la opción está activada; sin parámetro guardado cuenta como activada."""
    return env["ir.config_parameter"].sudo().get_param(PARAM_PREFIX + key, "1") != "0"


def active_view_options(env, model=None):
    """Devuelve las opciones de vistas activadas para el modelo (clave de caché de vistas)."""
    return tuple(
        key
        for key, spec in VIEW_OPTIONS.items()
        if (model is None or model in spec.get("models", PRODUCT_MODELS))
        and is_option_active(env, key)
    )


def hide_option_nodes(env, arch, view_type, model):
    """Oculta en la arquitectura de la vista los elementos de las opciones activadas."""
    attribute = "column_invisible" if view_type == "list" else "invisible"
    for key in active_view_options(env, model):
        for item in VIEW_OPTIONS[key].get(view_type, ()):
            xpath, node_attribute, value = (
                (item + ("1",))[:3] if isinstance(item, tuple) else (item, attribute, "1")
            )
            for node in arch.xpath(xpath):
                if node_attribute == "remove":
                    node.getparent().remove(node)
                else:
                    node.set(node_attribute, value)


def comfort_product_form(env, arch, view_type):
    """Ficha de producto más legible: letra más grande y, si los campos de tipo
    están ocultos, el bloque de precios pasa a la columna izquierda vacía."""
    if view_type != "form" or not is_option_active(env, "product_form_comfort"):
        return
    for form in arch.xpath("/form"):
        form.set("class", " ".join(filter(None, [form.get("class"), "o_simplify_product_form"])))
    if not is_option_active(env, "hide_product_type_fields"):
        return
    left = arch.xpath("//page[@name='general_information']//group[@name='group_general']")
    right = arch.xpath("//page[@name='general_information']//group[@name='group_standard_price']")
    if not left or not right:
        return
    right = right[0]
    categ = right.xpath("./field[@name='categ_id']")
    if not categ:
        return
    stop = right.index(categ[0])
    for node in list(right)[:stop]:
        left[0].append(node)
