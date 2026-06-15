##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import ValidationError
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestAccountCardInstallment(TransactionCase):
    """Pruebas del cálculo de recargo/reintegro y de las constraints.

    Correr con:
      odoo -d <db> -i card_installment --test-enable --test-tags card_installment
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.card = cls.env["account.card"].create({"name": "Test Visa"})

    def _make_installment(self, **vals):
        base = {
            "card_id": self.card.id,
            "name": vals.pop("name", "Plan"),
            "divisor": vals.pop("divisor", 1),
            "installment": vals.pop("installment", 1),
            "surcharge_coefficient": vals.pop("surcharge_coefficient", 1.0),
            "bank_discount": vals.pop("bank_discount", 0.0),
        }
        base.update(vals)
        return self.env["account.card.installment"].create(base)

    # ---- map_installment_values ----

    def test_surcharge_basic(self):
        """Recargo del 6% sin reintegro sobre 1000."""
        inst = self._make_installment(surcharge_coefficient=1.06, divisor=3)
        v = inst.map_installment_values(1000)

        self.assertAlmostEqual(v["base_amount"], 1000.00, places=2)
        self.assertAlmostEqual(v["amount"], 1060.00, places=2)
        self.assertAlmostEqual(v["fee"], 60.00, places=2)
        self.assertAlmostEqual(v["discount"], 0.00, places=2)
        self.assertAlmostEqual(v["final_amount"], 1060.00, places=2)
        # cuota: 1060 / 3 = 353.33
        self.assertIn("353.33", v["description"])

    def test_discount_applied_on_total_with_surcharge(self):
        """El reintegro se calcula sobre el total YA con recargo, y reduce el total."""
        inst = self._make_installment(surcharge_coefficient=1.10, bank_discount=5.0, divisor=1)
        v = inst.map_installment_values(1000)

        self.assertAlmostEqual(v["amount"], 1100.00, places=2)      # 1000 * 1.10
        self.assertAlmostEqual(v["discount"], 55.00, places=2)      # 5% de 1100
        self.assertAlmostEqual(v["final_amount"], 1045.00, places=2)  # 1100 - 55
        self.assertAlmostEqual(v["fee"], 100.00, places=2)

    def test_coefficient_precision_not_truncated(self):
        """El coeficiente conserva >2 decimales (antes 1.0625 se truncaba a 1.06)."""
        inst = self._make_installment(surcharge_coefficient=1.0625, divisor=1)
        v = inst.map_installment_values(1000)

        self.assertAlmostEqual(v["coefficient"], 1.0625, places=5)
        self.assertAlmostEqual(v["amount"], 1062.50, places=2)
        self.assertAlmostEqual(v["fee"], 62.50, places=2)

    def test_coefficient_precision_demo_value(self):
        """Valor real de demo (1.205) no se redondea a 1.21."""
        inst = self._make_installment(surcharge_coefficient=1.205, divisor=3)
        v = inst.map_installment_values(100)

        self.assertAlmostEqual(v["amount"], 120.50, places=2)
        self.assertAlmostEqual(v["fee"], 20.50, places=2)

    def test_installment_amount_uses_final_amount(self):
        """La cuota se divide sobre el total a cobrar (recargo - reintegro)."""
        inst = self._make_installment(surcharge_coefficient=1.10, bank_discount=10.0, divisor=2)
        v = inst.map_installment_values(1000)

        self.assertAlmostEqual(v["amount"], 1100.00, places=2)
        self.assertAlmostEqual(v["discount"], 110.00, places=2)
        self.assertAlmostEqual(v["final_amount"], 990.00, places=2)
        # 990 / 2 = 495.00
        self.assertIn("495.00", v["description"])
        self.assertIn("990.00", v["description"])

    def test_no_surcharge_no_discount(self):
        """Coeficiente 1.0 sin reintegro: no cambia el total."""
        inst = self._make_installment(surcharge_coefficient=1.0, divisor=1)
        v = inst.map_installment_values(1234.56)

        self.assertAlmostEqual(v["amount"], 1234.56, places=2)
        self.assertAlmostEqual(v["fee"], 0.00, places=2)
        self.assertAlmostEqual(v["final_amount"], 1234.56, places=2)

    def test_zero_amount(self):
        """Monto 0 no rompe y devuelve ceros."""
        inst = self._make_installment(surcharge_coefficient=1.06, bank_discount=5.0, divisor=3)
        v = inst.map_installment_values(0)

        self.assertAlmostEqual(v["amount"], 0.00, places=2)
        self.assertAlmostEqual(v["fee"], 0.00, places=2)
        self.assertAlmostEqual(v["discount"], 0.00, places=2)
        self.assertAlmostEqual(v["final_amount"], 0.00, places=2)

    def test_rounding_half_up(self):
        """Redondeo HALF_UP: 1.00 * 1.005 -> 1.01."""
        inst = self._make_installment(surcharge_coefficient=1.005, divisor=1)
        v = inst.map_installment_values(1.00)
        self.assertAlmostEqual(v["amount"], 1.01, places=2)

    def test_bank_discount_unset_no_crash(self):
        """bank_discount sin definir (0/False) no rompe el cálculo del reintegro."""
        inst = self._make_installment(surcharge_coefficient=1.06, divisor=1)
        inst.bank_discount = False
        v = inst.map_installment_values(500)
        self.assertAlmostEqual(v["discount"], 0.00, places=2)
        self.assertAlmostEqual(v["final_amount"], 530.00, places=2)

    # ---- card_installment_tree ----

    def test_card_installment_tree_structure(self):
        i1 = self._make_installment(name="3 cuotas", surcharge_coefficient=1.06, divisor=3)
        i2 = self._make_installment(name="6 cuotas", surcharge_coefficient=1.11, divisor=6)

        tree = (i1 | i2).card_installment_tree(1000)

        self.assertIn(self.card.id, tree)
        node = tree[self.card.id]
        self.assertEqual(node["id"], self.card.id)
        self.assertEqual(node["name"], self.card.name)
        self.assertEqual(len(node["installments"]), 2)
        names = {i["name"] for i in node["installments"]}
        self.assertEqual(names, {"3 cuotas", "6 cuotas"})

    def test_card_installment_tree_multi_card(self):
        card2 = self.env["account.card"].create({"name": "Test Master"})
        i1 = self._make_installment(name="A", divisor=1)
        i2 = self.env["account.card.installment"].create({
            "card_id": card2.id, "name": "B", "divisor": 1,
            "installment": 1, "surcharge_coefficient": 1.0,
        })
        tree = (i1 | i2).card_installment_tree(1000)
        self.assertEqual(set(tree.keys()), {self.card.id, card2.id})
        self.assertEqual(len(tree[self.card.id]["installments"]), 1)
        self.assertEqual(len(tree[card2.id]["installments"]), 1)

    # ---- display_name ----

    def test_display_name(self):
        inst = self._make_installment(name="Cuota simple 3", divisor=3)
        self.assertEqual(inst.display_name, "Cuota simple 3 (Test Visa)")

    # ---- constraint _check_divisor ----

    @mute_logger("odoo.sql_db")
    def test_divisor_zero_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_installment(divisor=0)

    @mute_logger("odoo.sql_db")
    def test_divisor_negative_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_installment(divisor=-3)

    def test_divisor_one_accepted(self):
        inst = self._make_installment(divisor=1)
        self.assertEqual(inst.divisor, 1)

    @mute_logger("odoo.sql_db")
    def test_divisor_write_zero_rejected(self):
        inst = self._make_installment(divisor=3)
        with self.assertRaises(ValidationError):
            inst.divisor = 0

    @mute_logger("odoo.sql_db")
    def test_surcharge_coefficient_negative_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_installment(surcharge_coefficient=-0.05)

    @mute_logger("odoo.sql_db")
    def test_surcharge_coefficient_negative_write_rejected(self):
        inst = self._make_installment(surcharge_coefficient=1.05)
        with self.assertRaises(ValidationError):
            inst.surcharge_coefficient = -0.1

    @mute_logger("odoo.sql_db")
    def test_bank_discount_negative_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_installment(bank_discount=-5.0)

    @mute_logger("odoo.sql_db")
    def test_bank_discount_over_100_rejected(self):
        with self.assertRaises(ValidationError):
            self._make_installment(bank_discount=105.0)
