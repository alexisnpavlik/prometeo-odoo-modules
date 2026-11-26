from odoo.tests import tagged

from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon


@tagged("post_install", "-at_install")
class TestWeightByAmountTour(TestPointOfSaleHttpCommon):
    """Botón $ → kg: el importe ingresado fija la cantidad del producto por peso."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        kg = cls.env.ref("uom.product_uom_kgm")
        values = {"available_in_pos": True, "sale_ok": True, "taxes_id": [(5, 0, 0)], "to_weight": False}
        product = cls.env["product.product"]
        product.create({**values, "name": "PWA Queso", "uom_id": kg.id, "uom_po_id": kg.id, "list_price": 8000})
        product.create({**values, "name": "PWA Fiambre", "uom_id": kg.id, "uom_po_id": kg.id, "list_price": 7000})
        product.create({**values, "name": "PWA Unidad", "list_price": 500})

    def test_pos_weight_by_amount_tour(self):
        self.start_pos_tour("pos_weight_by_amount_tour")
