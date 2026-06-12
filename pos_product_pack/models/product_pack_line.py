# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, models


class ProductPackLine(models.Model):
    _name = "product.pack.line"
    _inherit = ["product.pack.line", "pos.load.mixin"]

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ["id", "parent_product_id", "quantity", "product_id"]
