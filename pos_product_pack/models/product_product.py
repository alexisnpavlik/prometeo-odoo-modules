# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields = super()._load_pos_data_fields(config_id)
        fields.extend(["pack_ok", "pack_type", "pack_component_price"])
        return fields

    def _add_missing_products(self, products, config_id, data):
        """Fuerza la carga de los componentes de los packs cargados.

        El POS precarga como mucho `point_of_sale.limited_product_count`
        productos. Si un componente queda fuera de ese set, el frontend no lo
        encuentra al explotar el pack y la línea nunca se crea. Odoo hace esta
        misma protección para los combos (`get_limited_products_loading`), pero
        no conoce los packs de OCA.
        """
        super()._add_missing_products(products, config_id, data)

        loaded_ids = {product["id"] for product in products}
        if not loaded_ids:
            return

        pack_lines = (
            self.env["product.pack.line"]
            .sudo()
            .search([("parent_product_id", "in", list(loaded_ids))])
        )
        missing_ids = set(pack_lines.product_id.ids) - loaded_ids
        if missing_ids:
            products.extend(
                self._load_product_with_domain(
                    [("id", "in", list(missing_ids))], config_id
                )
            )
