# -*- coding: utf-8 -*-
import logging
import threading
from contextlib import ExitStack
from uuid import uuid4

from psycopg2.errors import SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.exceptions import UserError
from odoo.modules.registry import Registry
from odoo.tests.common import BaseCase, get_db_name, tagged
from odoo.tools import mute_logger

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestCviPaymentConcurrency(BaseCase):
    """Dos conexiones reales: nunca reutilizar el cursor de TransactionCase."""

    def setUp(self):
        """Confirma únicamente fixtures propios para que ambos cursores los vean."""
        super().setUp()
        self.registry = Registry(get_db_name())
        self.assertIsNone(self.registry.test_cr, "Se requieren cursores PostgreSQL reales")
        self.context = {"tracking_disable": True, "mail_create_nosubscribe": True}
        with self.registry.cursor() as cr:
            self._set_timeouts(cr)
            env = api.Environment(cr, SUPERUSER_ID, self.context)
            self.company_id = env.company.id
            self.context["allowed_company_ids"] = [self.company_id]
            customer = env["cvi.customer"].create({
                "name": "CVI concurrency test", "dni": uuid4().hex,
                "company_id": self.company_id,
            })
            product = env["product.product"].create({
                "name": "CVI concurrency test", "available_in_pos": False,
            })
            frequency = (
                "weekly" if env.company.cvi_allowed_frequencies == "weekly" else "monthly"
            )
            plan = env["cvi.product.plan"].create({
                "product_tmpl_id": product.product_tmpl_id.id,
                "name": "CVI concurrency test", "installment_count": 2,
                "installment_amount": 10000.0, "frequency": frequency,
            })
            card = env["cvi.card"].create({
                "name": "CVI concurrency test", "customer_id": customer.id,
                "company_id": self.company_id, "product_id": product.id,
                "plan_id": plan.id, "date_sale": "2026-01-15",
                "charge_day_month": 10, "charge_day_week": "0",
            })
            card._cvi_generate_installments()
            card.state = "active"
            payments = env["cvi.payment"].create([
                {"name": "CVI concurrency A", "card_id": card.id, "amount": 10000.0},
                {"name": "CVI concurrency B", "card_id": card.id, "amount": 10000.0},
            ])
            self.card_id = card.id
            self.installment_id = card.installment_ids.filtered(lambda i: not i.is_commission).id
            self.payment_ids = payments.ids
            self.customer_id = customer.id
            self.plan_id = plan.id
            self.template_id = product.product_tmpl_id.id
            # Register before commit so even a failing setup closes/cleans its fixtures.
            self.addCleanup(self._cleanup_fixtures)

    @staticmethod
    def _set_timeouts(cr):
        """Acota consultas y esperas de locks también durante setup/cleanup."""
        cr.execute("SET LOCAL lock_timeout = '10s'")
        cr.execute("SET LOCAL statement_timeout = '15s'")

    def _cleanup_fixtures(self):
        """Borra por IDs propios; nunca modifica registros previos de calidad."""
        with self.registry.cursor() as cr:
            self._set_timeouts(cr)
            env = api.Environment(cr, SUPERUSER_ID, self.context)
            payments = env["cvi.payment"].browse(self.payment_ids).exists()
            payments.allocation_ids.unlink()
            # Test-only cleanup of committed fixtures; no production deletion bypass.
            payments.write({"state": "draft"})
            payments.unlink()
            env["cvi.card"].browse(self.card_id).exists().unlink()
            env["cvi.product.plan"].browse(self.plan_id).exists().unlink()
            env["product.template"].browse(self.template_id).exists().unlink()
            env["cvi.customer"].browse(self.customer_id).exists().unlink()

    @mute_logger("odoo.sql_db")
    def test_concurrent_payments_cannot_overallocate_same_residual(self):
        """Dos snapshots con deuda 10000 no pueden confirmar imputaciones por 20000."""
        barrier = threading.Barrier(2, timeout=10)

        results = [None, None]
        errors = []

        def post(index, env, payment_id):
            """Lee antes de la barrera y confirma (o revierte) una transacción real."""
            try:
                cr = env.cr
                try:
                    self._set_timeouts(cr)
                    cr.execute("SELECT pg_backend_pid(), txid_current(), current_setting('transaction_isolation')")
                    identity = cr.fetchone()
                    self.assertEqual(identity[2], "repeatable read")
                    payment = env["cvi.payment"].browse(payment_id)
                    candidates = payment._cvi_target_installments()
                    self.assertEqual(candidates.ids, [self.installment_id])
                    self.assertEqual(candidates.amount_residual, 10000.0)
                    barrier.wait()
                    try:
                        payment.action_post()
                        # Include deferred stored computes and the real commit in the race.
                        cr.commit()
                    except SerializationFailure as exc:
                        query = cr._obj.query.decode()
                        cr.rollback()
                        _logger.info("CVI concurrent rejection: SQLSTATE=%s query=%s", exc.pgcode, query)
                        results[index] = payment_id, identity, "serialization_failure"
                        return
                    results[index] = payment_id, identity, "posted"
                except BaseException as exc:
                    errors.append(exc)
                    barrier.abort()
            finally:
                cr.rollback()

        with ExitStack() as stack:
            # The test loader holds Registry._lock in the main thread. Construct
            # environments here, then give each worker exclusive use of its cursor.
            envs = [
                api.Environment(stack.enter_context(self.registry.cursor()), SUPERUSER_ID, self.context)
                for _ in self.payment_ids
            ]
            threads = [
                threading.Thread(target=post, args=(index, env, payment_id), daemon=True)
                for index, (env, payment_id) in enumerate(zip(envs, self.payment_ids))
            ]
            for thread in threads:
                thread.start()
            try:
                for thread in threads:
                    thread.join(timeout=40)
            finally:
                barrier.abort()
                for thread, env in zip(threads, envs):
                    if thread.is_alive():
                        env.cr._cnx.cancel()
                        thread.join(timeout=20)
                self.assertFalse(any(thread.is_alive() for thread in threads), "Concurrent payment timed out")
            if errors:
                raise errors[0]

        _logger.info("CVI concurrent transactions: %s", results)
        self.assertEqual(len({result[1][0] for result in results}), 2, "Distinct PostgreSQL backends")
        self.assertEqual(len({result[1][1] for result in results}), 2, "Distinct PostgreSQL transactions")
        with self.registry.cursor() as cr:
            self._set_timeouts(cr)
            env = api.Environment(cr, SUPERUSER_ID, self.context)
            # Raw allocation sum detects overpayment even though amount_residual is clamped to zero.
            cr.execute("""
                SELECT COALESCE(SUM(a.amount), 0), COUNT(*)
                  FROM cvi_allocation a
                  JOIN cvi_payment p ON p.id = a.payment_id
                 WHERE a.installment_id = %s AND p.state = 'posted'
            """, [self.installment_id])
            self.assertEqual(cr.fetchone(), (10000.0, 1))
            self.assertCountEqual([result[2] for result in results], ["posted", "serialization_failure"])
            payments = env["cvi.payment"].browse(self.payment_ids)
            self.assertCountEqual(payments.mapped("state"), ["posted", "draft"])
            rejected = payments.filtered(lambda p: p.state == "draft")
            self.assertFalse(rejected.allocation_ids)
            installment = env["cvi.installment"].browse(self.installment_id)
            self.assertEqual(installment.amount_paid, 10000.0)
            self.assertEqual(installment.amount_residual, 0.0)
            # A fresh transaction (as in an RPC retry) sees the winner and rejects excess.
            with self.assertRaises(UserError), cr.savepoint():
                rejected.action_post()
            self.assertEqual(rejected.state, "draft")
            self.assertFalse(rejected.allocation_ids)
