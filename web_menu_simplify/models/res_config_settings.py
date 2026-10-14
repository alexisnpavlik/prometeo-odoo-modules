# -*- coding: utf-8 -*-

from odoo import api, fields, models

from .simplify_options import ALL_OPTIONS, PARAM_PREFIX, is_option_active

FIELD_PREFIX = "simplify_"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Un campo por opción: simplify_<opción>. Sin config_parameter a propósito,
    # ver get_values/set_values.
    # General
    simplify_hide_discuss = fields.Boolean("Ocultar Conversaciones")
    simplify_hide_dashboards = fields.Boolean("Ocultar Tableros")
    simplify_hide_link_tracker = fields.Boolean("Ocultar Rastreador de enlaces")
    simplify_hide_tests = fields.Boolean("Ocultar Pruebas")
    simplify_hide_sales = fields.Boolean("Ocultar Ventas")
    simplify_hide_systray = fields.Boolean("Ocultar chat y actividades de la barra superior")
    simplify_partner_form_simple = fields.Boolean("Ficha de contacto simplificada")
    simplify_flatten_single_menus = fields.Boolean("Menús de una sola opción como enlace directo")
    simplify_pos_first = fields.Boolean("Punto de venta primero y al iniciar sesión")
    # Compras
    simplify_purchase_simple = fields.Boolean("Compras simplificado")
    simplify_purchase_return_button = fields.Boolean("Botón Devolver en la orden de compra")
    simplify_purchase_confirm_receive = fields.Boolean("Confirmar e ingresar en un paso")
    simplify_hide_purchase_order_fields = fields.Boolean("Ocultar datos avanzados de la orden de compra")
    simplify_hide_purchase_order_send_print = fields.Boolean("Ocultar envío por correo e impresión de la orden")
    simplify_hide_purchase_order_taxes = fields.Boolean("Ocultar columna Impuestos en la orden de compra")
    simplify_hide_purchase_order_invoice = fields.Boolean("Ocultar botón Crear factura en la orden de compra")
    simplify_purchase_order_no_rfq = fields.Boolean("Orden de compra sin etapas de cotización")
    simplify_purchase_confirmed_only_return = fields.Boolean("Orden de compra sin botones redundantes")
    # Punto de venta
    simplify_hide_pos_reports = fields.Boolean("Ocultar Reportes de Punto de venta")
    simplify_hide_pos_categories = fields.Boolean("Ocultar Categorías de PdV")
    simplify_hide_pos_combos = fields.Boolean("Ocultar Opciones de los combos")
    simplify_hide_pos_printers = fields.Boolean("Ocultar Impresoras de preparación")
    simplify_hide_pos_note_models = fields.Boolean("Ocultar Modelos de nota")
    simplify_pos_invoices_menu = fields.Boolean("Menú Facturas en Punto de venta")
    # Facturación
    simplify_hide_account = fields.Boolean("Ocultar app Facturación")
    simplify_hide_account_dashboard = fields.Boolean("Ocultar Tablero de Facturación")
    simplify_hide_account_bank_cash = fields.Boolean("Ocultar Banco y Caja")
    simplify_hide_account_entries = fields.Boolean("Ocultar Contabilidad")
    simplify_hide_account_reports = fields.Boolean("Ocultar Reportes de Facturación")
    simplify_hide_account_ledgers = fields.Boolean("Ocultar Mayor de clientes y proveedores")
    # Inventario
    simplify_hide_stock_procurement = fields.Boolean("Ocultar Aprovisionamiento")
    simplify_hide_stock_lots = fields.Boolean("Ocultar Números de serie/lote")
    simplify_hide_stock_packages = fields.Boolean("Ocultar Paquetes")
    simplify_hide_stock_move_analysis = fields.Boolean("Ocultar Análisis de movimientos")
    simplify_hide_stock_valuation = fields.Boolean("Ocultar Valoración")
    simplify_inventory_open_products = fields.Boolean("Inventario abre en Productos")
    simplify_hide_stock_overview = fields.Boolean("Ocultar Información general")
    simplify_hide_stock_operations = fields.Boolean("Ocultar Operaciones")
    simplify_hide_update_quantity = fields.Boolean("Ocultar botón Actualizar cantidad")
    simplify_replenish_immediate = fields.Boolean("Reabastecer ingresa la mercadería al instante")
    simplify_replenish_buy_locked = fields.Boolean("Reabastecer siempre con la ruta Comprar")
    simplify_replenish_vendor_partner = fields.Boolean("Reabastecer: crear proveedor desde el asistente")
    simplify_stock_categories_menu = fields.Boolean("Menú Categorías en Inventario")
    # Productos
    simplify_hide_variants = fields.Boolean("Ocultar Variantes")
    simplify_hide_attributes = fields.Boolean("Ocultar Atributos")
    simplify_hide_pricelists = fields.Boolean("Ocultar Listas de precios")
    simplify_hide_product_documents = fields.Boolean("Ocultar Documentos")
    simplify_hide_product_forecast = fields.Boolean("Ocultar Pronosticado")
    simplify_hide_reordering_rules = fields.Boolean("Ocultar Reglas de reordenamiento")
    simplify_hide_product_type_fields = fields.Boolean("Ocultar tipo de producto, facturación e inventario")
    simplify_hide_product_sale_flags = fields.Boolean("Ocultar casillas Ventas, Compras y Punto de venta")
    simplify_hide_purchase_taxes = fields.Boolean("Ocultar Impuestos de compra")
    simplify_product_form_comfort = fields.Boolean("Ficha de producto más legible")

    @api.model
    def get_values(self):
        """Lee cada opción; sin parámetro guardado vale activada."""
        res = super().get_values()
        for key in ALL_OPTIONS:
            res[FIELD_PREFIX + key] = is_option_active(self.env, key)
        return res

    def set_values(self):
        """Guarda cada opción como "1"/"0" para que apagarla no borre el parámetro."""
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        for key in ALL_OPTIONS:
            params.set_param(PARAM_PREFIX + key, "1" if self[FIELD_PREFIX + key] else "0")
