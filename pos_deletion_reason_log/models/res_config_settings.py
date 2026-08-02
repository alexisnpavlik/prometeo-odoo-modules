# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    require_reason_order_deletion = fields.Boolean(
        related="pos_config_id.require_reason_order_deletion", readonly=False
    )
    require_reason_line_deletion = fields.Boolean(
        related="pos_config_id.require_reason_line_deletion", readonly=False
    )
    require_reason_qty_reduction = fields.Boolean(
        related="pos_config_id.require_reason_qty_reduction", readonly=False
    )
    require_reason_high_discount = fields.Boolean(
        related="pos_config_id.require_reason_high_discount", readonly=False
    )
    high_discount_threshold = fields.Float(
        related="pos_config_id.high_discount_threshold", readonly=False
    )
    require_reason_price_reduction = fields.Boolean(
        related="pos_config_id.require_reason_price_reduction", readonly=False
    )
    require_reason_price_increase = fields.Boolean(
        related="pos_config_id.require_reason_price_increase", readonly=False
    )
    block_close_with_pending_orders = fields.Boolean(
        related="pos_config_id.block_close_with_pending_orders", readonly=False
    )
    block_zero_price_payment = fields.Boolean(
        related="pos_config_id.block_zero_price_payment", readonly=False
    )
    block_negative_price_payment = fields.Boolean(
        related="pos_config_id.block_negative_price_payment", readonly=False
    )
    require_reason_note = fields.Boolean(
        related="pos_config_id.require_reason_note", readonly=False
    )
