from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInstallmentValues(TransactionCase):
    """Cálculo server-side de cuotas que usa el popup del POS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.card = cls.env["account.card"].create({"name": "Tarjeta Unit"})
        cls.plan_1 = cls.env["account.card.installment"].create({
            "card_id": cls.card.id, "name": "Plan 1", "installment": 1, "surcharge_coefficient": 1.0,
        })
        cls.plan_6 = cls.env["account.card.installment"].create({
            "card_id": cls.card.id, "name": "Plan 6", "installment": 6, "surcharge_coefficient": 1.10,
        })

    def test_positive_amount(self):
        """Monto positivo: base intacta, recargo = monto x (coef - 1)."""
        values = self.plan_6.map_installment_values(27000)
        self.assertEqual(values["base_amount"], 27000.0)
        self.assertAlmostEqual(values["amount"], 29700.0)
        self.assertAlmostEqual(values["fee"], 2700.0)

    def test_coefficient_one_has_no_fee(self):
        """Coeficiente 1: el recargo es 0 y la base no cambia."""
        values = self.plan_1.map_installment_values(19700)
        self.assertEqual(values["base_amount"], 19700.0)
        self.assertEqual(values["fee"], 0.0)

    def test_negative_amount_discount_line(self):
        """Línea de descuento global (precio negativo): el recargo también es proporcional y negativo."""
        values = self.plan_6.map_installment_values(-14010)
        self.assertEqual(values["base_amount"], -14010.0)
        self.assertAlmostEqual(values["amount"], -15411.0)
        self.assertAlmostEqual(values["fee"], -1401.0)

    def test_zero_amount(self):
        """Monto 0 (producto gratis): no rompe y no genera recargo."""
        values = self.plan_6.map_installment_values(0)
        self.assertEqual(values["base_amount"], 0.0)
        self.assertEqual(values["fee"], 0.0)

    def test_tree_groups_by_card(self):
        """card_installment_tree devuelve todos los planes activos bajo su tarjeta."""
        tree = (self.plan_1 | self.plan_6).card_installment_tree(1000)
        names = sorted(inst["name"] for inst in tree[self.card.id]["installments"])
        self.assertEqual(names, ["Plan 1", "Plan 6"])
