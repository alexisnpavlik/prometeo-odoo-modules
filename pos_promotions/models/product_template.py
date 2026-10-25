# -*- coding: utf-8 -*-

import logging

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_promotion_pack = fields.Boolean("Pack de promoción", copy=False)
    promotion_pack_line_ids = fields.One2many(
        "pos.promotion.pack.line", "pack_tmpl_id", string="Productos del pack", copy=True
    )
    promotion_pack_regular_price = fields.Float(
        "Precio normal", compute="_compute_promotion_pack_prices", digits="Product Price"
    )
    promotion_pack_saving = fields.Float(
        "Ahorro", compute="_compute_promotion_pack_prices", digits="Product Price"
    )

    @api.depends("list_price", "promotion_pack_line_ids.quantity", "promotion_pack_line_ids.product_id.lst_price")
    def _compute_promotion_pack_prices(self):
        """Precio de los productos sueltos y cuánto se ahorra con el pack."""
        for template in self:
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            template.promotion_pack_regular_price = regular
            template.promotion_pack_saving = regular - template.list_price if regular else 0.0

    @api.constrains("is_promotion_pack", "promotion_pack_line_ids")
    def _check_promotion_pack_lines(self):
        """Un pack necesita al menos un producto."""
        if any(template.is_promotion_pack and not template.promotion_pack_line_ids for template in self):
            raise ValidationError(_("Agregá al menos un producto al pack."))

    @api.model_create_multi
    def create(self, vals_list):
        """Arma los combos del POS de los packs nuevos. El pack nace como producto común y
        pasa a combo con sus combos ya armados: Odoo no deja crear un combo vacío."""
        for vals in vals_list:
            if vals.get("is_promotion_pack"):
                vals["type"] = "consu"
        templates = super().create(vals_list)
        packs = templates.filtered("is_promotion_pack")
        packs._sync_promotion_pack_combos()
        packs.write({"type": "combo"})
        return templates

    def write(self, vals):
        """Rearma los combos del POS si cambian los productos o el nombre del pack."""
        res = super().write(vals)
        if {"promotion_pack_line_ids", "name", "is_promotion_pack"} & set(vals):
            self.filtered("is_promotion_pack")._sync_promotion_pack_combos()
        return res

    def _sync_promotion_pack_combos(self):
        """Un combo de una sola opción por cada unidad de cada producto: el POS los agrega
        solos (sin elegir) y reparte el precio del pack entre los productos."""
        Combo = self.env["product.combo"].sudo()
        for template in self:
            old_combos = Combo.search([("promotion_pack_tmpl_id", "=", template.id)])
            combos = Combo.create([
                {
                    "name": f"{template.name}: {line.product_id.display_name}"
                    + (f" ({unit}/{line.quantity})" if line.quantity > 1 else ""),
                    "promotion_pack_tmpl_id": template.id,
                    "company_id": template.company_id.id,
                    "combo_item_ids": [Command.create({"product_id": line.product_id.id})],
                }
                for line in template.promotion_pack_line_ids
                for unit in range(1, line.quantity + 1)
            ])
            template.combo_ids = [Command.set(combos.ids)]
            old_combos.unlink()
            _logger.info("pos_promotions: pack %s con %s combos", template.display_name, len(combos))
