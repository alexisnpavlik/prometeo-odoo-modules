import logging

import odoo
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)

# Datos propios del escenario committeado de la prueba de concurrencia. No
# pueden coincidir con los del setUp: esos viven sin commitear en la transacción
# del test y sus índices únicos harían esperar al INSERT del otro cursor.
CONCURRENCY_MP_PAYMENT_ID = "170951482352"
CONCURRENCY_MP_USER_ID = "430185253"
CONCURRENCY_ACCOUNT_NAME = "Cuenta prueba concurrencia"


class ImputacionCommon(TransactionCase):
    """Escenario compartido: una cuenta, un pago disponible y líneas de cobro."""

    def setUp(self):
        super().setUp()
        self.account = self.env["mercadopago.account"].create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
        })
        self.payment = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482351",
            "account_id": self.account.id,
            "amount": 1500.0,
            "date_approved": "2026-08-03 15:21:49",
            "source": "qr",
            "state": "available",
        })

    def _make_pos_payment(self, amount=1500.0, env=None, account=None):
        """Crea una línea de pago mínima sobre la que imputar.

        Admite un entorno y una cuenta alternativos: la prueba de concurrencia
        arma su escenario en un cursor propio, fuera de la transacción del test.
        """
        env = env or self.env
        account = account or self.account
        journal = env["account.journal"].search([("type", "=", "bank")], limit=1)
        method = env["pos.payment.method"].create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": account.id, "mp_pos_id": "64365871",
        })
        config = env["pos.config"].create({"name": "Caja test"})
        config.write({"payment_method_ids": [(4, method.id)]})
        config.open_ui()
        session = config.current_session_id
        order = env["pos.order"].create({
            "session_id": session.id, "amount_total": amount, "amount_tax": 0,
            "amount_paid": 0, "amount_return": 0,
        })
        return env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": method.id, "amount": amount,
        })


@tagged("post_install", "-at_install")
class TestImputacionUnica(ImputacionCommon):
    def test_impute_links_and_locks(self):
        """Una imputación normal vincula el pago y lo saca de disponible."""
        line = self._make_pos_payment()
        self.payment.impute(line)
        self.assertEqual(self.payment.state, "matched")
        self.assertEqual(self.payment.pos_payment_id, line)
        self.assertEqual(self.payment.matched_by_user_id, self.env.user)
        self.assertTrue(self.payment.matched_at)

    def test_second_imputation_is_rejected(self):
        """Un pago ya imputado no se puede imputar de nuevo."""
        first = self._make_pos_payment()
        second = self._make_pos_payment()
        self.payment.impute(first)
        with self.assertRaises(UserError):
            self.payment.impute(second)


@tagged("post_install", "-at_install")
class TestImputacionConcurrente(ImputacionCommon):
    """La prueba de concurrencia vive en su propia clase, y por lo tanto en su
    propia transacción: escribe datos committeados en la base y eso haría fallar
    por serialización a cualquier otro test que compartiera el cursor de clase.
    """

    def _build_committed_scenario(self, registry):
        """Deja committeados en base el pago y las dos líneas que se lo disputan.

        TransactionCase de Odoo 18 prohíbe commit() sobre el cursor del test, así
        que el escenario se construye en un cursor propio: sin datos committeados
        los cursores rivales no verían nada sobre lo que competir.
        """
        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, self.env.uid, {})
            self._drop_committed_scenario(env)
            account = env["mercadopago.account"].create({
                "name": CONCURRENCY_ACCOUNT_NAME,
                "mode": "production",
                "mp_user_id": CONCURRENCY_MP_USER_ID,
            })
            payment = env["mercadopago.payment"].create({
                "mp_payment_id": CONCURRENCY_MP_PAYMENT_ID,
                "account_id": account.id,
                "amount": 1500.0,
                "date_approved": "2026-08-03 15:21:49",
                "source": "qr",
                "state": "available",
            })
            line_a = self._make_pos_payment(env=env, account=account)
            line_b = self._make_pos_payment(env=env, account=account)
            return payment.id, line_a.id, line_b.id

    def _drop_committed_scenario(self, env):
        """Borra de la base lo que el escenario committeado dejó escrito.

        Corre antes de armarlo y después de usarlo: una corrida abortada no debe
        dejar una sesión de POS abierta ni chocar contra el índice único del pago.
        """
        accounts = env["mercadopago.account"].with_context(active_test=False).search([
            ("name", "=", CONCURRENCY_ACCOUNT_NAME),
        ])
        if not accounts:
            return
        env["mercadopago.payment"].search([("account_id", "in", accounts.ids)]).unlink()
        methods = env["pos.payment.method"].search([("mp_account_id", "in", accounts.ids)])
        lines = env["pos.payment"].search([("payment_method_id", "in", methods.ids)])
        orders = lines.pos_order_id
        configs = methods.config_ids | orders.session_id.config_id
        sessions = env["pos.session"].search([("config_id", "in", configs.ids)])
        lines.unlink()
        orders.unlink()
        sessions.unlink()
        configs.unlink()
        methods.unlink()
        accounts.unlink()
        _logger.info("Escenario de concurrencia limpiado de la base de pruebas")

    def test_concurrent_imputation_yields_exactly_one(self):
        """Dos transacciones simultáneas sobre el mismo pago: una gana, una falla.

        Criterio de salida de la fase 3. Usa dos cursores reales para que el
        bloqueo de fila se ejerza de verdad, no simulado.
        """
        registry = self.registry
        payment_id, line_a_id, line_b_id = self._build_committed_scenario(registry)
        outcomes = []
        try:
            with registry.cursor() as cr_a, registry.cursor() as cr_b:
                env_a = odoo.api.Environment(cr_a, self.env.uid, {})
                env_b = odoo.api.Environment(cr_b, self.env.uid, {})
                payment_a = env_a["mercadopago.payment"].browse(payment_id)
                payment_b = env_b["mercadopago.payment"].browse(payment_id)

                payment_a.impute(env_a["pos.payment"].browse(line_a_id))
                outcomes.append("a")
                cr_a.commit()

                try:
                    with mute_logger("odoo.sql_db"):
                        payment_b.impute(env_b["pos.payment"].browse(line_b_id))
                    outcomes.append("b")
                    cr_b.commit()
                except Exception:
                    cr_b.rollback()

            self.assertEqual(outcomes, ["a"], "Se imputó más de una vez el mismo pago")
            with registry.cursor() as cr_check:
                env_check = odoo.api.Environment(cr_check, self.env.uid, {})
                imputed = env_check["mercadopago.payment"].browse(payment_id)
                self.assertEqual(imputed.pos_payment_id.id, line_a_id)
        finally:
            with registry.cursor() as cr_clean:
                self._drop_committed_scenario(
                    odoo.api.Environment(cr_clean, self.env.uid, {})
                )
