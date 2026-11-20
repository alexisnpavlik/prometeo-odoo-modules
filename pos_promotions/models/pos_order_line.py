# -*- coding: utf-8 -*-

from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    promotion_pack_tmpl_id = fields.Many2one(
        "product.template",
        string="Promoción",
        index="btree_not_null",
        help="Promoción que puso el descuento de la línea; sin promoción, el descuento lo puso el cajero.",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """El POS guarda qué pack puso el descuento, para no confundirlo con uno manual."""
        return super()._load_pos_data_fields(config_id) + ["promotion_pack_tmpl_id"]
