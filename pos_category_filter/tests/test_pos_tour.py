from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestCategoryFilterTour(TestPointOfSaleHttpCommon):
    """El POS de una caja filtrada: sin barra de categorías, escaneo bloqueado y Buscar más filtrado."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        categ = cls.env["product.category"]
        cancha = categ.create({"name": "CF Cancha"})
        biju = categ.create({"name": "CF Bijouterie"})
        values = {"available_in_pos": True, "sale_ok": True, "taxes_id": [(5, 0, 0)]}
        cls.env["product.product"].create({**values, "name": "CF Pelota", "categ_id": cancha.id, "barcode": "7790001", "list_price": 1000})
        collar = cls.env["product.product"].create({**values, "name": "CF Collar", "categ_id": biju.id, "barcode": "7790003", "list_price": 300})
        # Un combo de Cancha que lleva el Collar: el Collar se carga como ítem pero no se vende suelto.
        combo = cls.env["product.combo"].create({
            "name": "CF combo",
            "combo_item_ids": [(0, 0, {"product_id": collar.id, "extra_price": 0})],
        })
        cls.env["product.product"].create({**values, "name": "CF Combo", "type": "combo", "categ_id": cancha.id, "combo_ids": [(6, 0, combo.ids)], "list_price": 1200})
        cls.main_pos_config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, cancha.ids)]})

    def test_pos_category_filter_tour(self):
        self.start_pos_tour("pos_category_filter_tour")
