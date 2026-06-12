# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields.extend(["pack_ok", "pack_type", "pack_component_price"])
        return fields
