# -*- coding: utf-8 -*-
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    # NO sobrescribir _load_pos_data_fields en pos.config: el mixin devuelve []
    # a propósito, y una lista vacía hace que search_read cargue TODOS los campos
    # (incluido use_pricelist, que el core lee sin chequeo en _load_pos_data).
    # Devolver una lista acotada rompe el POS con KeyError: 'use_pricelist'.
    # Estos toggles llegan solos al frontend por la carga completa de pos.config.
    require_reason_order_deletion = fields.Boolean(
        string="Motivo al eliminar orden",
        default=True,
        help="Pide un motivo cuando el cajero elimina una orden completa.",
    )
    require_reason_line_deletion = fields.Boolean(
        string="Motivo al eliminar línea",
        default=True,
        help="Pide un motivo cuando el cajero borra una línea/producto de la orden.",
    )
    require_reason_qty_reduction = fields.Boolean(
        string="Motivo al reducir cantidad",
        default=True,
        help="Pide un motivo cuando el cajero reduce la cantidad de una línea.",
    )
    require_reason_high_discount = fields.Boolean(
        string="Motivo en descuento alto",
        default=True,
        help="Pide un motivo cuando el descuento de una línea supera el umbral configurado.",
    )
    high_discount_threshold = fields.Float(
        string="Umbral de descuento alto (%)",
        default=30.0,
        help="Porcentaje por encima del cual un descuento de línea se considera alto "
             "y requiere motivo. Hasta este valor inclusive no se pide motivo.",
    )
    require_reason_price_reduction = fields.Boolean(
        string="Motivo al reducir precio",
        default=True,
        help="Pide un motivo cuando el cajero baja el precio de una línea por debajo "
             "del que tenía al seleccionarla.",
    )
    require_reason_price_increase = fields.Boolean(
        string="Motivo al aumentar precio",
        default=True,
        help="Pide un motivo cuando el cajero sube el precio de una línea por encima "
             "del que tenía al seleccionarla.",
    )
    block_close_with_pending_orders = fields.Boolean(
        string="Bloquear cierre con órdenes pendientes",
        default=True,
        help="Impide cerrar la caja si quedan órdenes con productos sin finalizar. "
             "El cajero debe cobrarlas o cancelarlas (con motivo) antes de cerrar.",
    )
    block_zero_price_payment = fields.Boolean(
        string="Bloquear cobro con productos a precio 0",
        default=True,
        help="Impide pasar a la pantalla de pago si alguna línea de la orden tiene "
             "precio unitario 0. Evita cobrar productos sin precio cargado.",
    )
    block_negative_price_payment = fields.Boolean(
        string="Bloquear cobro con precio negativo",
        default=True,
        help="Impide pasar a la pantalla de pago si alguna línea tiene precio "
             "unitario negativo. Desactivalo si tu flujo de devoluciones usa "
             "precios negativos de forma legítima.",
    )
