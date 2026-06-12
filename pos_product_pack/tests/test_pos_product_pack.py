# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
from odoo import Command
from odoo.tests.common import TransactionCase


class TestPosProductPack(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Create component products (storable/consumable)
        cls.component1 = cls.env["product.product"].create(
            {
                "name": "Comp 1",
                "type": "consu",
                "list_price": 20,
            }
        )
        cls.component2 = cls.env["product.product"].create(
            {
                "name": "Comp 2",
                "type": "consu",
                "list_price": 30,
            }
        )

        # Create a non-detailed pack
        cls.pack = cls.env["product.product"].create(
            {
                "name": "Pack Non Detailed",
                "type": "consu",
                "list_price": 100,
                "pack_ok": True,
                "pack_type": "non_detailed",
                "pack_component_price": "ignored",
                "pack_line_ids": [
                    Command.create({"product_id": cls.component1.id, "quantity": 3}),
                    Command.create({"product_id": cls.component2.id, "quantity": 1}),
                ],
            }
        )

        # Retrieve warehouse and locations
        cls.picking_type = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing")], limit=1
        )
        if not cls.picking_type:
            cls.picking_type = cls.env["stock.picking.type"].search([], limit=1)

        cls.location = cls.env["stock.location"].search(
            [
                ("usage", "=", "internal"),
                "|",
                ("company_id", "=", cls.company.id),
                ("company_id", "=", False),
            ],
            limit=1,
        )
        cls.location_dest = cls.env["stock.location"].search(
            [
                ("usage", "=", "customer"),
                "|",
                ("company_id", "=", cls.company.id),
                ("company_id", "=", False),
            ],
            limit=1,
        )

        # Create POS config & session
        cls.pos_config = cls.env["pos.config"].create({"name": "Test POS"})
        cls.pos_session = cls.env["pos.session"].create({
            "config_id": cls.pos_config.id,
            "user_id": cls.env.user.id,
        })

        # Create a mock pos.order
        cls.pos_order = cls.env["pos.order"].create(
            {
                "name": "Test Order",
                "session_id": cls.pos_session.id,
                "company_id": cls.company.id,
                "amount_tax": 0.0,
                "amount_total": 200.0,
                "amount_paid": 200.0,
                "amount_return": 0.0,
            }
        )

        # Create a line with our pack product
        cls.pos_order_line = cls.env["pos.order.line"].create(
            {
                "order_id": cls.pos_order.id,
                "product_id": cls.pack.id,
                "qty": 2.0,
                "price_unit": 100.0,
                "price_subtotal": 200.0,
                "price_subtotal_incl": 200.0,
            }
        )

    def test_pos_non_detailed_pack_stock_picking(self):
        """Test that stock moves are correctly created for pack components in POS."""
        # Create a stock picking
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.location.id,
                "location_dest_id": self.location_dest.id,
                "company_id": self.company.id,
            }
        )

        # Generate stock moves
        picking._create_move_from_pos_order_lines(self.pos_order_line)

        # Find generated stock moves
        moves = picking.move_ids

        # We expect 2 stock moves (one for each component: Comp 1, Comp 2)
        # We do NOT expect any stock move for the pack itself
        self.assertEqual(len(moves), 2)
        self.assertNotIn(self.pack.id, moves.mapped("product_id.id"))

        # Verify Component 1 stock move (qty should be 2.0 pack qty * 3 component qty = 6.0)
        move_comp1 = moves.filtered(lambda m: m.product_id.id == self.component1.id)
        self.assertEqual(len(move_comp1), 1)
        self.assertEqual(move_comp1.product_uom_qty, 6.0)

        # Verify Component 2 stock move (qty should be 2.0 pack qty * 1 component qty = 2.0)
        move_comp2 = moves.filtered(lambda m: m.product_id.id == self.component2.id)
        self.assertEqual(len(move_comp2), 1)
        self.assertEqual(move_comp2.product_uom_qty, 2.0)
