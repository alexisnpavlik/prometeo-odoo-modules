# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.tests.common import RecordCapturer

from odoo.addons.base.tests.common import BaseCommon


class TestIntercompanyDelivery(BaseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company_obj = cls.env["res.company"]
        cls.company1 = company_obj.create({"name": "Company A"})
        cls.company2 = company_obj.create({"name": "Company B"})
        cls.user_demo = cls.env["res.users"].create(
            {
                "login": "firstnametest",
                "name": "User Demo",
                "email": "firstnametest@example.org",
                "company_id": cls.company1.id,
                "company_ids": [
                    Command.link(cls.company1.id),
                    Command.link(cls.company2.id),
                ],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.env.ref("stock.group_stock_user").id),
                ],
            }
        )
        # Se filtra por "code" (independiente del idioma) en vez de "name"
        # ("Delivery Orders" / "Receipts"), porque el "name" de
        # stock.picking.type está traducido y la base "calidad" tiene es_AR
        # como idioma base, donde esos registros se llaman "Órdenes de
        # entrega" / "Recepciones".
        cls.picking_type_1 = (
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
        cls.picking_type_2 = (
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

        cls.company1.intercompany_in_type_id = cls.picking_type_1.id
        cls.company2.intercompany_in_type_id = cls.picking_type_2.id
        cls.product1 = cls.env["product.product"].create(
            {
                "name": "Product A",
                "type": "consu",
                "is_storable": True,
                "categ_id": cls.env.ref("product.product_category_all").id,
                "qty_available": 100,
            }
        )
        cls.stock_location = (
            cls.env["stock.location"]
            .sudo()
            .search([("name", "=", "Stock"), ("company_id", "=", cls.company1.id)])
        )
        cls.uom_unit = cls.env.ref("uom.product_uom_unit")

    def test_picking_creation(self):
        stock_location = self.env["stock.location"].search(
            [("usage", "=", "internal"), ("company_id", "=", self.company1.id)]
        )
        custs_location = self.env.ref("stock.stock_location_customers")
        custs_location.company_id = False
        self.product1.company_id = False
        picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_demo)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": stock_location.id,
                    "location_dest_id": custs_location.id,
                    "picking_type_id": self.company1.intercompany_in_type_id.id,
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": stock_location.id,
                "location_dest_id": custs_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 1.0,
                "picking_id": picking.id,
            }
        )
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()

        counterpart_picking = rc.records
        self.assertEqual(len(counterpart_picking), 1)
        self.assertEqual(counterpart_picking.counterpart_of_picking_id, picking)
        self.assertEqual(len(counterpart_picking.move_ids), len(picking.move_ids))
        for cp_move, move in zip(
            counterpart_picking.move_ids, picking.move_ids, strict=False
        ):
            self.assertEqual(cp_move.counterpart_of_move_id, move)
        self.assertEqual(
            len(counterpart_picking.move_line_ids), len(picking.move_line_ids)
        )
        for cp_line, line in zip(
            counterpart_picking.move_line_ids, picking.move_line_ids, strict=False
        ):
            self.assertEqual(cp_line.counterpart_of_line_id, line)

    def test_counterpart_lines_belong_to_their_move(self):
        """Con dos moves del mismo producto en el origen, cada línea del
        espejo debe colgar del move espejo de su propio move de origen, y no
        de cualquier move espejo que comparta producto."""
        stock_location = self.env["stock.location"].search(
            [("usage", "=", "internal"), ("company_id", "=", self.company1.id)]
        )
        custs_location = self.env.ref("stock.stock_location_customers")
        custs_location.company_id = False
        self.product1.company_id = False
        picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_demo)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": stock_location.id,
                    "location_dest_id": custs_location.id,
                    "picking_type_id": self.company1.intercompany_in_type_id.id,
                }
            )
        )
        # Se crean con picking.env (usuario/contexto de picking) y no con
        # self.env, porque button_validate() corre como user_demo y ese
        # usuario no tiene permiso de escritura sobre moves creados con otro
        # usuario en este entorno multiempresa restringido.
        move_1 = picking.env["stock.move"].create(
            {
                "name": self.product1.name,
                "product_id": self.product1.id,
                "product_uom_qty": 3.0,
                "product_uom": self.uom_unit.id,
                "location_id": stock_location.id,
                "location_dest_id": custs_location.id,
                "picking_id": picking.id,
            }
        )
        move_2 = picking.env["stock.move"].create(
            {
                "name": self.product1.name,
                "product_id": self.product1.id,
                "product_uom_qty": 7.0,
                "product_uom": self.uom_unit.id,
                "location_id": stock_location.id,
                "location_dest_id": custs_location.id,
                "picking_id": picking.id,
            }
        )
        self.env["stock.move.line"].create(
            {
                "move_id": move_1.id,
                "picking_id": picking.id,
                "location_id": stock_location.id,
                "location_dest_id": custs_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 3.0,
            }
        )
        self.env["stock.move.line"].create(
            {
                "move_id": move_2.id,
                "picking_id": picking.id,
                "location_id": stock_location.id,
                "location_dest_id": custs_location.id,
                "product_id": self.product1.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 7.0,
            }
        )
        # Fija la premisa del test: si el origen llegara a _action_done con
        # los dos moves fusionados en uno, el resto de las aserciones se
        # cumplirían trivialmente sin cubrir la regresión que motiva este
        # test (ver ronda de corrección 1 del review).
        self.assertEqual(
            len(picking.move_ids),
            2,
            "El picking de origen no llegó con dos moves separados: "
            "la premisa del test no se sostiene",
        )

        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()

        counterpart = rc.records
        self.assertEqual(len(counterpart), 1)
        self.assertEqual(len(counterpart.move_ids), 2)
        self.assertEqual(len(counterpart.move_line_ids), 2)
        self.assertTrue(counterpart.move_line_ids)
        for line in counterpart.move_line_ids:
            self.assertTrue(
                line.move_id,
                "La línea %s del espejo quedó sin move asociado" % line.id,
            )
            self.assertEqual(
                line.move_id.counterpart_of_move_id,
                line.counterpart_of_line_id.move_id,
                "La línea del espejo cuelga de un move que no es el espejo del suyo",
            )
            self.assertEqual(
                line.quantity,
                line.counterpart_of_line_id.quantity,
                "La cantidad de la línea del espejo no corresponde a la de origen",
            )
