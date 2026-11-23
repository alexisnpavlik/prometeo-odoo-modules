import json
from unittest import skipUnless

from odoo.tests import tagged

from odoo.addons.prometeo_ai_agent.agent import prompts, tools

from .common import AiAgentCase


@tagged("post_install", "-at_install")
class TestSumExpression(AiAgentCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partners = cls.env["res.partner"].create([{"name": "SE P%s" % i, "color": i + 1} for i in range(3)])

    def setUp(self):
        super().setUp()
        self.uenv = self.env(user=self.agent_user)
        self.ctx = tools.new_context()

    def call(self, env=None, **arguments):
        return json.loads(tools.execute_tool(env or self.uenv, self.ctx, "sum_expression", arguments))

    def test_sums_expression_per_record(self):
        domain = json.dumps([["id", "in", self.partners.ids]])
        res = self.call(model="res.partner", domain=domain, groupby=[], expressions=["color * 2 + 1"])
        self.assertEqual(res["totals"]["color * 2 + 1"], (1 + 2 + 3) * 2 + 3)
        self.assertEqual(res["records"], 3)

    def test_rejects_code_and_non_numeric_fields(self):
        for expr in ("__import__('os')", "name * 2", "color ** 2", "max(color, 1)"):
            res = self.call(model="res.partner", domain="[]", groupby=[], expressions=[expr])
            self.assertIn("error", res, expr)

    def test_rejects_secret_and_blocked_paths(self):
        res = self.call(model="res.partner", domain="[]", groupby=[], expressions=["user_id.password"])
        self.assertIn("error", res)

    def test_groupby_only_direct_fields(self):
        res = self.call(model="res.partner", domain="[]", groupby=["create_date:month"], expressions=["color"])
        self.assertIn("read_group", res["error"])

    @skipUnless("product.pricelist", "requiere product")
    def test_sale_price_and_cost_by_branch(self):
        if "stock.quant" not in self.env:
            self.skipTest("requiere stock")
        company = self.env.company
        product = self.env["product.product"].create({
            "name": "SE Producto", "is_storable": True, "list_price": 100.0, "standard_price": 40.0})
        pricelist = self.env["product.pricelist"].create({
            "name": "SE Lista", "company_id": company.id, "sequence": 1,
            "item_ids": [(0, 0, {"applied_on": "1_product", "product_tmpl_id": product.product_tmpl_id.id,
                                 "compute_price": "fixed", "fixed_price": 150.0})]})
        if "pos.config" in self.env:
            self.env["pos.config"].search([("company_id", "=", company.id)]).write({"pricelist_id": pricelist.id})
        stock = self.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1).lot_stock_id
        self.env["stock.quant"]._update_available_quantity(product, stock, 3.0)
        res = self.call(env=self.env, model="stock.quant",
                        domain=json.dumps([["product_id", "=", product.id], ["location_id", "=", stock.id]]),
                        groupby=["company_id"],
                        expressions=["quantity * sale_price(product_id)", "quantity * cost(product_id)"])
        self.assertEqual(res["totals"]["quantity * sale_price(product_id)"], 450.0)
        self.assertEqual(res["totals"]["quantity * cost(product_id)"], 120.0)
        self.assertEqual(res["products_at_zero"], {"sale_price": 0, "cost": 0})

    @skipUnless("product.pricelist", "requiere product")
    def test_fast_prices_match_odoo(self):
        products = self.env["product.product"].search([], limit=60)
        categ = products[:1].categ_id
        pricelist = self.env["product.pricelist"].create({"name": "SE Comparar", "item_ids": [
            (0, 0, {"applied_on": "1_product", "product_tmpl_id": products[0].product_tmpl_id.id,
                    "compute_price": "fixed", "fixed_price": 7.0}),
            (0, 0, {"applied_on": "0_product_variant", "product_id": products[1].id,
                    "compute_price": "percentage", "percent_price": 10}),
            (0, 0, {"applied_on": "2_product_category", "categ_id": categ.id,
                    "compute_price": "percentage", "percent_price": 5}),
            (0, 0, {"applied_on": "3_global", "compute_price": "fixed", "fixed_price": 1.0, "min_quantity": 5}),
        ]})
        expected = pricelist._get_products_price(products, 1.0)
        self.assertEqual(tools._fast_pricelist_prices(pricelist, products), expected)


@tagged("post_install", "-at_install")
class TestPromptContext(AiAgentCase):

    def test_active_branch_and_business_notes_in_prompt(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "prometeo_ai_agent.business_notes", "La Caja Mayorista vende al por mayor.")
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertIn("Sucursal activa (la que el usuario ve en pantalla): %s" % self.agent_user.company_id.name, p)
        self.assertIn("La Caja Mayorista vende al por mayor.", p)
        self.assertIn("sum_expression", p)

    def test_no_notes_section_when_empty(self):
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.business_notes", "")
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertNotIn("Notas del negocio", p)
