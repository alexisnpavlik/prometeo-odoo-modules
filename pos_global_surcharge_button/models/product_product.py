from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _load_pos_data(self, data):
        """Fuerza la carga del producto de recargo en el POS si está activo."""
        res = super()._load_pos_data(data)
        config_id = self.env["pos.config"].browse(data["pos.config"]["data"][0]["id"])
        surcharge_product_id = config_id.surcharge_product_id.id
        product_ids_set = {product["id"] for product in res["data"]}

        if (
            config_id.enable_surcharge
            and surcharge_product_id
            and surcharge_product_id not in product_ids_set
        ):
            product_model = self.env["product.product"].with_context(
                {**self.env.context, "display_default_code": False}
            )
            product = product_model.search_read(
                [("id", "=", surcharge_product_id)], fields=res["fields"], load=False
            )
            self._process_pos_ui_product_product(product, config_id)
            res["data"].extend(product)

        return res
