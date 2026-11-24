from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPackLineMerge(TransactionCase):
    """Al guardar una promoción, las líneas del mismo producto se juntan sumando cantidades."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        values = {"available_in_pos": True, "sale_ok": True}
        cls.desk = cls.env["product.product"].create({**values, "name": "PLM Escritorio", "list_price": 1799})
        cls.pen = cls.env["product.product"].create({**values, "name": "PLM Lapicera", "list_price": 1.2})

    def _lines(self, pack):
        return sorted((line.product_id.name, line.quantity) for line in pack.promotion_pack_line_ids)

    def test_create_merges_same_product(self):
        pack = self.env["product.template"].create({
            "name": "PLM Pack", "list_price": 100, "available_in_pos": True, "is_promotion_pack": True,
            "promotion_pack_line_ids": [
                Command.create({"product_id": self.desk.id, "quantity": 1}),
                Command.create({"product_id": self.pen.id, "quantity": 2}),
                Command.create({"product_id": self.desk.id, "quantity": 1}),
            ],
        })
        self.assertEqual(self._lines(pack), [("PLM Escritorio", 2), ("PLM Lapicera", 2)])

    def test_write_merges_same_product(self):
        pack = self.env["product.template"].create({
            "name": "PLM Pack 2", "list_price": 100, "available_in_pos": True, "is_promotion_pack": True,
            "promotion_pack_line_ids": [Command.create({"product_id": self.desk.id, "quantity": 1})],
        })
        pack.write({"promotion_pack_line_ids": [Command.create({"product_id": self.desk.id, "quantity": 3})]})
        self.assertEqual(self._lines(pack), [("PLM Escritorio", 4)])
