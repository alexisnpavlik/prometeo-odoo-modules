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


class TestPosDetailedProductPack(TransactionCase):
    """Packs 'detailed': el frontend explota el pack en una línea por componente.

    Si un componente no está entre los productos precargados en el POS
    (point_of_sale.limited_product_count), esa línea nunca se crea y el stock
    del componente nunca se descuenta.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.component1 = cls.env["product.product"].create(
            {"name": "Comp Det 1", "type": "consu", "is_storable": True}
        )
        cls.component2 = cls.env["product.product"].create(
            {"name": "Comp Det 2", "type": "consu", "is_storable": True}
        )
        cls.pack = cls.env["product.product"].create(
            {
                "name": "Pack Detailed",
                "type": "consu",
                "list_price": 100,
                "pack_ok": True,
                "pack_type": "detailed",
                "pack_component_price": "ignored",
                "pack_line_ids": [
                    Command.create({"product_id": cls.component1.id, "quantity": 3}),
                    Command.create({"product_id": cls.component2.id, "quantity": 1}),
                ],
            }
        )

        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1
        )
        cls.picking_type = cls.warehouse.out_type_id
        cls.location = cls.warehouse.lot_stock_id
        cls.location_dest = cls.env["stock.location"].search(
            [
                ("usage", "=", "customer"),
                "|",
                ("company_id", "=", cls.company.id),
                ("company_id", "=", False),
            ],
            limit=1,
        )

        cls.pos_config = cls.env["pos.config"].create({"name": "Test POS Detailed"})
        cls.pos_session = cls.env["pos.session"].create(
            {"config_id": cls.pos_config.id, "user_id": cls.env.user.id}
        )

    def _new_order(self):
        return self.env["pos.order"].create(
            {
                "session_id": self.pos_session.id,
                "company_id": self.company.id,
                "amount_tax": 0.0,
                "amount_total": 100.0,
                "amount_paid": 100.0,
                "amount_return": 0.0,
            }
        )

    def _add_line(self, order, product, qty, is_pack_component=False):
        return self.env["pos.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "qty": qty,
                "price_unit": 0.0,
                "price_subtotal": 0.0,
                "price_subtotal_incl": 0.0,
                "is_pack_component": is_pack_component,
            }
        )

    def _new_picking(self):
        return self.env["stock.picking"].create(
            {
                "picking_type_id": self.picking_type.id,
                "location_id": self.location.id,
                "location_dest_id": self.location_dest.id,
                "company_id": self.company.id,
            }
        )

    def _qty_by_product(self, moves):
        return {m.product_id.id: m.product_uom_qty for m in moves}

    def test_pack_components_are_force_loaded_in_pos(self):
        """Los componentes se cargan aunque queden fuera del set precargado."""
        products = [{"id": self.pack.id}]
        data = {"pos.order.line": {"data": []}}

        self.env["product.product"]._add_missing_products(
            products, self.pos_config.id, data
        )

        loaded_ids = {p["id"] for p in products}
        self.assertIn(self.component1.id, loaded_ids)
        self.assertIn(self.component2.id, loaded_ids)

    def test_missing_component_lines_still_move_stock(self):
        """Sin líneas de componente, el backend igual descuenta el pack completo."""
        order = self._new_order()
        pack_line = self._add_line(order, self.pack, 2.0)
        picking = self._new_picking()

        picking._create_move_from_pos_order_lines(pack_line)

        qty = self._qty_by_product(picking.move_ids)
        self.assertNotIn(self.pack.id, qty)
        self.assertEqual(qty.get(self.component1.id), 6.0)
        self.assertEqual(qty.get(self.component2.id), 2.0)

    def test_component_lines_are_not_deducted_twice(self):
        """Con las líneas de componente presentes no se duplica el descuento."""
        order = self._new_order()
        lines = self._add_line(order, self.pack, 2.0)
        lines |= self._add_line(order, self.component1, 6.0, is_pack_component=True)
        lines |= self._add_line(order, self.component2, 2.0, is_pack_component=True)
        picking = self._new_picking()

        picking._create_move_from_pos_order_lines(lines)

        qty = self._qty_by_product(picking.move_ids)
        self.assertNotIn(self.pack.id, qty)
        self.assertEqual(qty.get(self.component1.id), 6.0)
        self.assertEqual(qty.get(self.component2.id), 2.0)

    def test_only_the_missing_component_is_completed(self):
        """Si falta una sola línea de componente, se completa solo esa."""
        order = self._new_order()
        lines = self._add_line(order, self.pack, 2.0)
        lines |= self._add_line(order, self.component1, 6.0, is_pack_component=True)
        picking = self._new_picking()

        picking._create_move_from_pos_order_lines(lines)

        qty = self._qty_by_product(picking.move_ids)
        self.assertEqual(qty.get(self.component1.id), 6.0)
        self.assertEqual(qty.get(self.component2.id), 2.0)

    def test_standalone_sale_of_a_component_is_not_credited_to_the_pack(self):
        """Un componente vendido suelto no tapa el descuento del pack."""
        order = self._new_order()
        lines = self._add_line(order, self.pack, 1.0)
        lines |= self._add_line(order, self.component1, 3.0, is_pack_component=True)
        lines |= self._add_line(order, self.component2, 1.0, is_pack_component=True)
        # el cliente además se lleva un Comp Det 1 suelto
        lines |= self._add_line(order, self.component1, 1.0)
        picking = self._new_picking()

        picking._create_move_from_pos_order_lines(lines)

        qty = self._qty_by_product(picking.move_ids)
        self.assertEqual(qty.get(self.component1.id), 4.0)
        self.assertEqual(qty.get(self.component2.id), 1.0)
