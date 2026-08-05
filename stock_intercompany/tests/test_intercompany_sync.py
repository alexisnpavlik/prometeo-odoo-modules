# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.tests.common import RecordCapturer

from odoo.addons.base.tests.common import BaseCommon


class SyncCommon(BaseCommon):
    @classmethod
    def setUpClass(cls):
        """Base común para los tests de sincronización intercompany:
        dos compañías, un usuario con acceso a ambas y un producto y
        ubicaciones compartidos entre ellas."""
        super().setUpClass()
        company_obj = cls.env["res.company"]
        cls.company1 = company_obj.create({"name": "Sync Company A"})
        cls.company2 = company_obj.create({"name": "Sync Company B"})
        cls.group_stock_user = cls.env.ref("stock.group_stock_user")
        # NOTA: el grupo stock_intercompany.group_intercompany_manager recién
        # se crea en la Tarea 4. Se deja comentado a propósito; la Tarea 4
        # debe descomentar esta línea al agregar el grupo.
        # cls.group_manager = cls.env.ref(
        #     "stock_intercompany.group_intercompany_manager"
        # )
        cls.user_operator = cls.env["res.users"].create(
            {
                "login": "sync_operator",
                "name": "Operador",
                "email": "sync_operator@example.org",
                "company_id": cls.company1.id,
                "company_ids": [
                    Command.link(cls.company1.id),
                    Command.link(cls.company2.id),
                ],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.group_stock_user.id),
                ],
            }
        )
        # Se filtra por "code" (independiente del idioma) en vez de "name"
        # ("Delivery Orders" / "Receipts"), porque el "name" de
        # stock.picking.type está traducido y la base "calidad" tiene es_AR
        # como idioma base, donde esos registros se llaman "Órdenes de
        # entrega" / "Recepciones".
        cls.picking_type_out = (
            cls.env["stock.picking.type"]
            .sudo()
            .search(
                [
                    ("company_id", "=", cls.company1.id),
                    ("code", "=", "outgoing"),
                ],
                limit=1,
            )
        )
        cls.picking_type_in = (
            cls.env["stock.picking.type"]
            .sudo()
            .search(
                [
                    ("company_id", "=", cls.company2.id),
                    ("code", "=", "incoming"),
                ],
                limit=1,
            )
        )
        cls.company1.intercompany_in_type_id = cls.picking_type_out.id
        cls.company2.intercompany_in_type_id = cls.picking_type_in.id
        cls.product = cls.env["product.product"].create(
            {
                "name": "Sync Product",
                "type": "consu",
                "is_storable": True,
                "categ_id": cls.env.ref("product.product_category_all").id,
            }
        )
        cls.product.company_id = False
        cls.product2 = cls.env["product.product"].create(
            {
                "name": "Sync Product 2",
                "type": "consu",
                "is_storable": True,
                "categ_id": cls.env.ref("product.product_category_all").id,
            }
        )
        cls.product2.company_id = False
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")
        cls.stock_location = cls.env["stock.location"].search(
            [("usage", "=", "internal"), ("company_id", "=", cls.company1.id)],
            limit=1,
        )
        cls.custs_location = cls.env.ref("stock.stock_location_customers")
        cls.custs_location.company_id = False

    def _create_delivery(self, qty=10.0, product=None):
        """Crea y valida una entrega intercompany. Devuelve (entrega, recepción)."""
        product = product or self.product
        picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_operator)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.company1.intercompany_in_type_id.id,
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "product_id": product.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": qty,
                "picking_id": picking.id,
            }
        )
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()
        return picking, rc.records


class TestCounterpartResolution(SyncCommon):
    def test_counterpart_resolves_in_both_directions(self):
        """La contraparte se resuelve desde la entrega y desde la recepción."""
        delivery, reception = self._create_delivery()
        self.assertEqual(reception.counterpart_picking_id, delivery)
        self.assertEqual(delivery.counterpart_picking_id, reception)

    def test_no_counterpart_is_empty(self):
        """Un picking sin espejo devuelve un recordset vacío, no un error."""
        picking = self.env["stock.picking"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "picking_type_id": self.picking_type_out.id,
            }
        )
        self.assertFalse(picking.counterpart_picking_id)
