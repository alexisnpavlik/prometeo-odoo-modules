# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductCombo(models.Model):
    _inherit = "product.combo"

    promotion_pack_tmpl_id = fields.Many2one(
        "product.template",
        string="Pack de promoción",
        ondelete="cascade",
        index=True,
        help="Pack que generó este combo; se regenera al cambiar los componentes del pack.",
    )
