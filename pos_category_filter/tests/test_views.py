from lxml import etree

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCategoryFilterViews(TransactionCase):
    """Ajustes muestran el filtro nuevo; las Categorías de PdV quedan ocultas."""

    def _arch(self, model, view_xmlid):
        view = self.env.ref(view_xmlid)
        arch = self.env[model].get_views([(view.id, "form")])["views"]["form"]["arch"]
        return etree.fromstring(arch)

    def test_settings_show_new_fields(self):
        arch = self._arch("res.config.settings", "point_of_sale.res_config_settings_view_form")
        self.assertTrue(arch.xpath("//field[@name='pos_category_filter_mode']"))
        self.assertTrue(arch.xpath("//field[@name='pos_category_filter_ids']"))

    def test_settings_hide_native_limit(self):
        arch = self._arch("res.config.settings", "point_of_sale.res_config_settings_view_form")
        setting = arch.xpath("//setting[.//field[@name='pos_limit_categories']]")[0]
        self.assertEqual(setting.get("invisible"), "1")

    def test_product_form_hides_pos_category(self):
        arch = self._arch("product.template", "product.product_template_form_view")
        for node in arch.xpath("//field[@name='pos_categ_ids']"):
            self.assertEqual(node.get("invisible"), "1")

    def test_settings_writes_config(self):
        config = self.env["pos.config"].create({"name": "CF Caja ajustes"})
        categ = self.env["product.category"].create({"name": "CF Ajustes"})
        settings = self.env["res.config.settings"].create({
            "pos_config_id": config.id,
            "pos_category_filter_mode": "exclude",
            "pos_category_filter_ids": [(6, 0, categ.ids)],
        })
        settings.execute()
        self.assertEqual(config.category_filter_mode, "exclude")
        self.assertEqual(config.category_filter_ids, categ)

    def test_pos_category_menu_hidden(self):
        menu = self.env.ref("point_of_sale.menu_products_pos_category")
        self.assertEqual(menu.groups_id, self.env.ref("base.group_no_one"))
