import logging
import threading

from psycopg2 import errors as psycopg2_errors

import odoo
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)

# Tiempos de la prueba de concurrencia. El lock_timeout es sólo una red para que
# un lock que no se libere mate al hilo en vez de colgar la suite entera.
THREAD_START_SECONDS = 10.0
CONTENTION_SECONDS = 1.0
LOCK_TIMEOUT_SECONDS = 30

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

    def test_revert_frees_both_sides_of_the_link(self):
        """Reimputar tras revertir deja los dos lados del vínculo consistentes.

        Si revert() no limpiara el back-link, la línea vieja y la nueva quedarían
        apuntando las dos al mismo pago y la conciliación contaría el cobro dos
        veces: el índice único no lo ve, porque vive del otro lado.
        """
        line_a = self._make_pos_payment()
        line_b = self._make_pos_payment()

        self.payment.impute(line_a)
        self.assertEqual(line_a.mercadopago_payment_id, self.payment)

        self.payment.revert(reason="cobro asignado a la venta equivocada")
        self.assertFalse(line_a.mercadopago_payment_id)
        self.assertFalse(line_a.mercadopago_reference)
        self.assertFalse(self.payment.pos_payment_id)
        self.assertEqual(self.payment.state, "available")

        # Reimputar en la misma transacción: sin el flush previo al FOR UPDATE
        # esta llamada leería todavía "matched" y sería un rechazo falso.
        self.payment.impute(line_b)
        self.assertFalse(line_a.mercadopago_payment_id)
        self.assertEqual(line_b.mercadopago_payment_id, self.payment)
        self.assertEqual(self.payment.pos_payment_id, line_b)

    def test_line_already_linked_is_rejected(self):
        """Una línea ya vinculada a otro pago se rechaza antes del índice único."""
        line = self._make_pos_payment()
        other = self.env["mercadopago.payment"].create({
            "mp_payment_id": "170951482399",
            "account_id": self.account.id,
            "amount": 1500.0,
            "date_approved": "2026-08-03 15:25:00",
            "source": "qr",
            "state": "available",
        })
        self.payment.impute(line)
        with self.assertRaises(UserError):
            other.impute(line)

    def test_revert_requires_an_imputed_payment(self):
        """Revertir un pago disponible no hace nada y avisa con un UserError."""
        with self.assertRaises(UserError):
            self.payment.revert()


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
        Nunca propaga: si fallara, enmascararía el fallo real del test.
        """
        try:
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
        except Exception:
            env.cr.rollback()
            _logger.exception(
                "No se pudo limpiar el escenario de concurrencia: quedan datos "
                "committeados en la base de pruebas"
            )

    def test_concurrent_imputation_yields_exactly_one(self):
        """Dos transacciones simultáneas sobre el mismo pago: una gana, una falla.

        Criterio de salida de la fase 3. El segundo intento corre en un hilo con
        su propio cursor mientras el primero mantiene el lock tomado y sin
        commitear: así se ejerce la contención de fila de verdad, no el chequeo
        de estado sobre una fila ya committeada. Se afirma que el segundo espera
        y que después falla.
        """
        registry = self.registry
        uid = self.env.uid
        payment_id, line_a_id, line_b_id = self._build_committed_scenario(registry)
        outcomes = []
        expected_errors = []
        unexpected_errors = []
        second_started = threading.Event()
        second_finished = threading.Event()

        def impute_from_second_cashier():
            """Segundo cajero: hilo propio y cursor propio, contra el mismo pago."""
            try:
                with registry.cursor() as cr_b:
                    # Red de seguridad: si el lock no se libera, el hilo muere
                    # solo en vez de colgar la suite entera.
                    cr_b.execute("SET LOCAL lock_timeout = '%ss'" % LOCK_TIMEOUT_SECONDS)
                    env_b = odoo.api.Environment(cr_b, uid, {})
                    payment_b = env_b["mercadopago.payment"].browse(payment_id)
                    line_b = env_b["pos.payment"].browse(line_b_id)
                    second_started.set()
                    try:
                        with mute_logger("odoo.sql_db"):
                            payment_b.impute(line_b)
                        outcomes.append("b")
                    # Lista blanca deliberadamente angosta: el rechazo válido es
                    # el UserError del chequeo de estado tras el FOR UPDATE, o a
                    # lo sumo un fallo de serialización de Postgres. Aceptar
                    # `psycopg2.Error` entero incluía IntegrityError, así que si
                    # el bloqueo de fila se rompiera y el rechazo llegara recién
                    # por violación del índice único -la red final, no el
                    # mecanismo bajo prueba- el test daría verde igual.
                    except (UserError, psycopg2_errors.SerializationFailure) as error:
                        expected_errors.append(error)
                        _logger.info(
                            "El segundo cajero fue rechazado con %s: %s",
                            type(error).__name__, str(error).strip(),
                        )
                        cr_b.rollback()
            except Exception as error:  # cualquier otra cosa rompe el test
                unexpected_errors.append(error)
            finally:
                second_finished.set()

        second = threading.Thread(target=impute_from_second_cashier, daemon=True)
        try:
            cr_a = registry.cursor()
            try:
                env_a = odoo.api.Environment(cr_a, uid, {})
                payment_a = env_a["mercadopago.payment"].browse(payment_id)
                payment_a.impute(env_a["pos.payment"].browse(line_a_id))
                outcomes.append("a")

                # El primero todavía no commitea: retiene el lock de la fila.
                second.start()
                self.assertTrue(
                    second_started.wait(THREAD_START_SECONDS),
                    "El segundo cajero nunca llegó a intentar la imputación",
                )
                self.assertFalse(
                    second_finished.wait(CONTENTION_SECONDS),
                    "El segundo intento no esperó: el bloqueo de fila no se ejerció",
                )
                cr_a.commit()
            finally:
                cr_a.close()

            second.join(timeout=LOCK_TIMEOUT_SECONDS + THREAD_START_SECONDS)
            self.assertFalse(second.is_alive(), "El segundo intento quedó colgado en el lock")
            # Con la lista blanca angosta, un lock_timeout ya no entra en
            # expected_errors sino en unexpected_errors; se mira primero y en
            # las dos listas para que el diagnóstico siga siendo el específico
            # y no el genérico de "falló por algo inesperado".
            self.assertFalse(
                [e for e in expected_errors + unexpected_errors
                 if isinstance(e, psycopg2_errors.LockNotAvailable)],
                "El segundo intento murió por lock_timeout, no por el estado del pago",
            )
            self.assertFalse(
                unexpected_errors,
                "El segundo intento falló por algo inesperado: %s" % unexpected_errors,
            )
            self.assertTrue(expected_errors, "El segundo intento no falló")
            self.assertEqual(outcomes, ["a"], "Se imputó más de una vez el mismo pago")

            with registry.cursor() as cr_check:
                env_check = odoo.api.Environment(cr_check, uid, {})
                imputed = env_check["mercadopago.payment"].browse(payment_id)
                self.assertEqual(imputed.pos_payment_id.id, line_a_id)
                self.assertEqual(imputed.state, "matched")
                losing_line = env_check["pos.payment"].browse(line_b_id)
                self.assertFalse(losing_line.mercadopago_payment_id)
        finally:
            second.join(timeout=LOCK_TIMEOUT_SECONDS)
            with registry.cursor() as cr_clean:
                self._drop_committed_scenario(
                    odoo.api.Environment(cr_clean, uid, {})
                )
