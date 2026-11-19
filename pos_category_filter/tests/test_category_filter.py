from odoo.tests import TransactionCase, tagged

from odoo.addons.pos_category_filter.hooks import post_init_hook


@tagged("post_install", "-at_install")
class TestCategoryFilter(TransactionCase):
    """Filtro de productos por categoría de producto en cada caja."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        categ = cls.env["product.category"]
        cls.parent = categ.create({"name": "CF Padre"})
        cls.child = categ.create({"name": "CF Hija", "parent_id": cls.parent.id})
        cls.other = categ.create({"name": "CF Otra"})
        product = cls.env["product.product"]
        values = {"available_in_pos": True, "sale_ok": True, "type": "consu"}
        cls.p_parent = product.create({**values, "name": "CF prod padre", "categ_id": cls.parent.id, "barcode": "CF0001"})
        cls.p_child = product.create({**values, "name": "CF prod hija", "categ_id": cls.child.id, "barcode": "CF0002"})
        cls.p_other = product.create({**values, "name": "CF prod otra", "categ_id": cls.other.id, "barcode": "CF0003"})
        cls.ours = cls.p_parent | cls.p_child | cls.p_other
        cls.config = cls.env["pos.config"].create({"name": "CF Caja"})

    def _loaded(self):
        """Productos de prueba que la caja descargaría."""
        domain = self.config._get_available_product_domain()
        return self.env["product.product"].search(domain) & self.ours

    def test_mode_all_loads_everything(self):
        self.assertEqual(self.config.category_filter_mode, "all")
        self.assertEqual(self._loaded(), self.ours)

    def test_include_parent_includes_child(self):
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.parent.ids)]})
        self.assertEqual(self._loaded(), self.p_parent | self.p_child)

    def test_exclude(self):
        self.config.write({"category_filter_mode": "exclude", "category_filter_ids": [(6, 0, self.parent.ids)]})
        self.assertEqual(self._loaded(), self.p_other)

    def test_empty_list_behaves_as_all(self):
        for mode in ("include", "exclude"):
            self.config.write({"category_filter_mode": mode, "category_filter_ids": [(5, 0, 0)]})
            self.assertEqual(self.config._get_category_filter_domain(), [])
            self.assertEqual(self._loaded(), self.ours)

    def test_promotion_pack_kept(self):
        if "is_promotion_pack" not in self.env["product.template"]._fields:
            self.skipTest("pos_promotions no instalado")
        self.p_other.lst_price = 100
        pack = self.env["product.product"].create({
            "name": "CF pack",
            "available_in_pos": True,
            "sale_ok": True,
            "type": "consu",
            "categ_id": self.other.id,
            "list_price": 80,
            "is_promotion_pack": True,
            "promotion_pack_line_ids": [(0, 0, {"product_id": self.p_other.id, "quantity": 1})],
        })
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.parent.ids)]})
        loaded = self.env["product.product"].search(self.config._get_available_product_domain())
        self.assertIn(pack, loaded)
        self.assertIn(self.p_other, loaded, "el componente del pack también se carga")

    def test_hook_disables_native_limit(self):
        pos_categ = self.env["pos.category"].create({"name": "CF PdV"})
        self.config.write({"limit_categories": True, "iface_available_categ_ids": [(6, 0, pos_categ.ids)]})
        post_init_hook(self.env)
        self.assertFalse(self.config.limit_categories)

    def test_barcode_blocked_when_excluded(self):
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.other.ids)]})
        self.assertTrue(self.config.is_barcode_blocked_by_category("CF0001"))

    def test_barcode_allowed(self):
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.other.ids)]})
        self.assertFalse(self.config.is_barcode_blocked_by_category("CF0003"))

    def test_barcode_unknown_not_blocked(self):
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.other.ids)]})
        self.assertFalse(self.config.is_barcode_blocked_by_category("0000000000000"))

    def test_find_product_by_barcode_hides_excluded(self):
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.other.ids)]})
        self.config.open_ui()
        session = self.config.current_session_id
        result = session.find_product_by_barcode("CF0001", self.config.id)
        found_ids = [row["id"] for row in result.get("product.product", [])]
        self.assertNotIn(self.p_parent.id, found_ids)
        allowed = session.find_product_by_barcode("CF0003", self.config.id)
        self.assertIn(self.p_other.id, [row["id"] for row in allowed["product.product"]])

    def test_barcode_blocked_by_packaging(self):
        self.env["product.packaging"].create({"name": "CF caja x6", "product_id": self.p_parent.id, "qty": 6, "barcode": "CF0006"})
        self.config.write({"category_filter_mode": "include", "category_filter_ids": [(6, 0, self.other.ids)]})
        self.assertTrue(self.config.is_barcode_blocked_by_category("CF0006"))
