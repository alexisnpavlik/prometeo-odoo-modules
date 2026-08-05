# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import RecordCapturer

from odoo.addons.base.tests.common import BaseCommon

from odoo.addons.stock_intercompany.models.intercompany_sync import as_propagation


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
        cls.group_manager = cls.env.ref(
            "stock_intercompany.group_intercompany_manager"
        )
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
        cls.user_manager_both = cls.env["res.users"].create(
            {
                "login": "sync_manager_both",
                "name": "Manager Ambas",
                "email": "sync_manager_both@example.org",
                "company_id": cls.company1.id,
                "company_ids": [
                    Command.link(cls.company1.id),
                    Command.link(cls.company2.id),
                ],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.group_stock_user.id),
                    Command.link(cls.group_manager.id),
                ],
            }
        )
        cls.user_manager_one = cls.env["res.users"].create(
            {
                "login": "sync_manager_one",
                "name": "Manager Una",
                "email": "sync_manager_one@example.org",
                "company_id": cls.company1.id,
                "company_ids": [Command.link(cls.company1.id)],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.group_stock_user.id),
                    Command.link(cls.group_manager.id),
                ],
            }
        )

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
        self.assertEqual(picking.state, "done", "La entrega no quedó validada")
        self.assertEqual(
            len(rc.records), 1, "Se creó más de un picking en el bloque"
        )
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

    def test_counterpart_picking_id_refreshes_after_validate(self):
        """Leer counterpart_picking_id en la entrega antes de validar no debe
        dejarlo cacheado vacío para siempre.

        El compute depende de counterpart_of_picking_id, campo que solo
        llena el espejo apuntando a la entrega: `depends()` no puede
        rastrear la búsqueda inversa que hace `get_counterpart`. Si algo
        (por ejemplo un guard durante action_confirm/button_validate) lee
        el campo antes de que el espejo exista, queda cacheado vacío;
        `_create_counterpart_picking` tiene que invalidarlo a mano apenas
        crea el espejo para que una lectura posterior lo recalcule.
        """
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
                "product_id": self.product.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 10.0,
                "picking_id": picking.id,
            }
        )
        # Lectura previa a validar: cachea vacío, como haría un guard que
        # corre durante action_confirm/button_validate antes de que exista
        # el espejo (caso de la Tarea 4: can_edit_done).
        self.assertFalse(picking.counterpart_picking_id)
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()
        self.assertEqual(picking.state, "done", "La entrega no quedó validada")
        self.assertEqual(len(rc.records), 1, "Se creó más de un picking en el bloque")
        self.assertEqual(
            picking.counterpart_picking_id,
            rc.records,
            "counterpart_picking_id quedó rancio (vacío) en la entrega "
            "tras crear el espejo",
        )


class TestEditGuard(SyncCommon):
    def test_operator_cannot_edit_validated(self):
        """El operador no puede tocar una entrega intercompany ya validada."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        with self.assertRaises(AccessError):
            line.with_user(self.user_operator).write({"quantity": 5.0})

    def test_manager_with_one_company_cannot_edit(self):
        """El manager sin acceso a las dos compañías tampoco puede."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        with self.assertRaises(AccessError):
            line.with_user(self.user_manager_one).write({"quantity": 5.0})

    def test_manager_with_both_companies_can_edit(self):
        """El manager con las dos compañías sí puede."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        line.with_user(self.user_manager_both).write({"quantity": 5.0})
        self.assertEqual(line.quantity, 5.0)

    def test_can_edit_done_flag(self):
        """El campo que gobierna el readonly de la vista refleja las dos condiciones."""
        delivery, _reception = self._create_delivery()
        self.assertFalse(delivery.with_user(self.user_operator).can_edit_done)
        self.assertFalse(delivery.with_user(self.user_manager_one).can_edit_done)
        self.assertTrue(delivery.with_user(self.user_manager_both).can_edit_done)

    def test_plain_picking_is_untouched(self):
        """Un picking sin contraparte no queda sujeto al guard."""
        picking = (
            self.env["stock.picking"]
            .with_user(self.user_operator)
            .create(
                {
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "product_id": self.product.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 3.0,
                "picking_id": picking.id,
            }
        )
        picking.action_confirm()
        picking.button_validate()
        line = picking.move_line_ids[0]
        line.with_user(self.user_operator).write({"quantity": 2.0})
        self.assertEqual(line.quantity, 2.0)

    def test_propagation_bypasses_guard(self):
        """Una escritura propagada desde la contraparte no pasa por el guard.

        Es la excepción central de la regla de negocio: as_propagation()
        deja la escritura en sudo con el flag skip_intercompany_sync, y el
        guard tiene que dejarla pasar aunque el usuario en curso (el
        operador, sin el rol de manager) no cumpla ninguna de las dos
        condiciones. Si esto se rompe, todo el sync bidireccional de las
        tareas siguientes se estrella contra el guard.
        """
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        propagated_line = as_propagation(line.with_user(self.user_operator))
        propagated_line.write({"quantity": 7.0})
        self.assertEqual(line.quantity, 7.0)
