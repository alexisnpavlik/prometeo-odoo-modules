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
    simplify_hide_systray = fields.Boolean("Ocultar chat y actividades de la barra superior")
    # Punto de venta
    simplify_hide_pos_reports = fields.Boolean("Ocultar Reportes de Punto de venta")
    simplify_hide_pos_categories = fields.Boolean("Ocultar Categorías de PdV")
    simplify_hide_pos_combos = fields.Boolean("Ocultar Opciones de los combos")
    simplify_hide_pos_printers = fields.Boolean("Ocultar Impresoras de preparación")
    simplify_hide_pos_note_models = fields.Boolean("Ocultar Modelos de nota")
    # Facturación
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
    # Productos
    simplify_hide_variants = fields.Boolean("Ocultar Variantes")
    simplify_hide_attributes = fields.Boolean("Ocultar Atributos")
    simplify_hide_pricelists = fields.Boolean("Ocultar Listas de precios")
    simplify_hide_product_documents = fields.Boolean("Ocultar Documentos")
    simplify_hide_reordering_rules = fields.Boolean("Ocultar Reglas de reordenamiento")

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
