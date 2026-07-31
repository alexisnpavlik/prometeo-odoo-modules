# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviFullFlow(CviCommon):
    """Recorre el circuito del spec: fábrica -> vendedor -> cliente -> cobrador -> saldada."""

    def test_full_circuit_from_factory_to_settled_card(self):
        # Fechas de venta y cobro fijas en el pasado (ver tests/test_payment.py): sin
        # tolerancia amplia, las cuotas de cobranza quedarían "overdue" en vez de
        # "partial"/"pending" por el solo paso del tiempo real, rompiendo asserts que
        # no tienen que ver con mora.
        self.company.cvi_overdue_days = 3650  # ~10 años
        stock_location = self.warehouse.lot_stock_id
        quant_model = self.env["stock.quant"]

        # 1. La fábrica ingresa producción (HU-01).
        quant_model.with_context(inventory_mode=True).create({
            "product_id": self.product.id,
            "location_id": stock_location.id,
            "inventory_quantity": 20,
        }).action_apply_inventory()

        # 2. El depósito entrega 3 muebles al vendedor (HU-02).
        delivery = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": self.vendor_user.id,
            "direction": "out",
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 3})],
        })
        action = delivery.action_confirm_delivery()
        picking = self.env["stock.picking"].browse(action["res_id"])
        self.assertEqual(picking.state, "done")
        vendor_location = self.vendor_user.cvi_stock_location_id

        # 3. El vendedor carga la venta en el domicilio (HU-05, HU-06).
        card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "quantity": 1.0,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        card.action_confirm()
        self.assertEqual(card.state, "sold")
        self.assertEqual(len(card.installment_ids), 3)

        # 4. La primera cuota es la comisión del vendedor (HU-09, RN-01).
        first = card.installment_ids.filtered(lambda i: i.sequence == 1)
        self.assertEqual(first.state, "paid")
        self.assertTrue(card.payment_ids.filtered("is_commission"))

        # 5. El mueble salió del stock del vendedor (HU-03).
        self.assertEqual(
            quant_model._get_available_quantity(self.product, vendor_location),
            502,  # 500 del fixture + 3 entregados - 1 vendido
        )

        # 6. El vendedor enruta la tarjeta al cobrador (HU-10, HU-11).
        route = self.env["cvi.route.wizard"].create({
            "card_ids": [(6, 0, card.ids)],
            "collector_id": self.collector_user.id,
        })
        route.action_confirm_route()
        self.assertEqual(card.state, "routed")

        # 7. El cobrador la acepta y entra en su cartera (HU-12, RN-02).
        card.with_user(self.collector_user).action_accept()
        self.assertEqual(card.state, "active")

        # 8. Cobra la cuota 2 completa y parte de la 3 (HU-15).
        payment = self.env["cvi.payment"].create({
            "card_id": card.id, "amount": 14000.0, "date": "2026-02-10",
        })
        payment.action_post()
        self.assertEqual(card.amount_residual, 6000.0)
        self.assertEqual(
            card.installment_ids.filtered(lambda i: i.sequence == 2).state, "paid"
        )
        self.assertEqual(
            card.installment_ids.filtered(lambda i: i.sequence == 3).state, "partial"
        )

        # 9. Cobra el resto y la tarjeta se cierra sola (HU-17).
        rest = self.env["cvi.payment"].create({
            "card_id": card.id, "amount": 6000.0, "date": "2026-03-10",
        })
        rest.action_post()
        self.assertEqual(card.amount_residual, 0.0)
        self.assertEqual(card.state, "done")

        # 10. El vendedor devuelve a fábrica los 2 muebles que no vendió (HU-04).
        before = quant_model._get_available_quantity(self.product, stock_location)
        giveback = self.env["cvi.vendor.delivery.wizard"].create({
            "vendor_id": self.vendor_user.id,
            "direction": "in",
            "line_ids": [(0, 0, {"product_id": self.product.id, "quantity": 2})],
        })
        giveback.action_confirm_delivery()
        self.assertEqual(
            quant_model._get_available_quantity(self.product, stock_location), before + 2
        )
