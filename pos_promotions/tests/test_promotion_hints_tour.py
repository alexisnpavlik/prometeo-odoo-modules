from odoo import Command
from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon

PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


@tagged("post_install", "-at_install")
class TestPromotionHintsTour(TestPointOfSaleHttpCommon):
    """Burbujas de promociones incompletas en la pantalla de productos."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        values = {"available_in_pos": True, "sale_ok": True, "taxes_id": [(5, 0, 0)]}
        Product = cls.env["product.product"]
        vaso = Product.create({**values, "name": "PH Vaso", "list_price": 900, "default_code": "123"})
        fernet = Product.create({**values, "name": "PH Fernet", "list_price": 7000})
        coca = Product.create({**values, "name": "PH Coca", "list_price": 3200, "image_1920": PNG_1X1, "default_code": "7790895"})
        agua = Product.create({**values, "name": "PH Agua", "list_price": 1000})
        company = cls.main_pos_config.company_id

        def pack(name, price, lines):
            return cls.env["product.template"].create({
                **values,
                "name": name,
                "list_price": price,
                "is_promotion_pack": True,
                "promotion_price_mode": "fixed",
                "promotion_company_ids": [Command.set(company.ids)],
                "promotion_pack_line_ids": [
                    Command.create({"product_id": product.id, "quantity": qty}) for product, qty in lines
                ],
            })

        pack("Promo 2 Vasos", 1500, [(vaso, 2)])
        pack("Promo Fernet Coca", 9000, [(fernet, 1), (coca, 1)])
        # Más cara que los sueltos (2 × 1.000): no ahorra, nunca se sugiere.
        pack("Promo Agua cara", 2500, [(agua, 2)])

    def test_promotion_hints_tour(self):
        self.start_pos_tour("pos_promotion_hints_tour")
