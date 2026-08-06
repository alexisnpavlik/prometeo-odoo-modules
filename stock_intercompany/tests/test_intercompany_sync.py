# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.exceptions import AccessError, UserError
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

    def _create_delivery_with_backorder(
        self, demand_qty=10.0, validated_qty=4.0, product=None
    ):
        """Crea una entrega intercompany parcial y confirma el backorder.

        Reproduce el camino real de stock.picking._create_backorder()
        (stock/models/stock_picking.py): valida menos cantidad de la
        demandada, así que Odoo reparenta el remanente a un picking de
        backorder escribiendo picking_id sobre las líneas del origen
        DESPUÉS de que los moves de este ya están "done" (con el picking
        origen ya en state "done" y, siendo intercompany, con el espejo ya
        creado). Es el camino que la Tarea 4 no cubría y que motivó la
        regresión Critical de la ronda de corrección 2: sin un test que
        pase por acá, sacar o poner picking_id en GUARDED_LINE_FIELDS no
        se nota en la suite.

        A diferencia de _create_delivery (que crea la línea directo con
        la cantidad final y no pasa por una reserva real), acá hace falta
        stock disponible y una reserva real (action_assign): si no hay
        nada reservado, el move remanente que separa Odoo para el
        backorder queda sin líneas propias y el camino de
        _create_backorder que se quiere ejercitar no se dispara — el
        picking_id vigilado nunca llega a escribirse sobre una línea real
        y el test no detectaría la regresión.

        Corre siempre con user_operator (sin el rol), porque es
        justamente el operador normal quien tiene que poder validar una
        entrega parcial sin necesitar el rol de manager.
        """
        product = product or self.product
        self.env["stock.quant"].sudo()._update_available_quantity(
            product, self.stock_location, demand_qty
        )
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
        self.env["stock.move"].with_user(self.user_operator).create(
            {
                "name": product.name,
                "product_id": product.id,
                "product_uom_qty": demand_qty,
                "product_uom": self.uom_unit.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "picking_id": picking.id,
            }
        )
        picking.with_user(self.user_operator).action_confirm()
        picking.with_user(self.user_operator).action_assign()
        line = picking.move_line_ids
        self.assertTrue(line, "La reserva no generó una línea de movimiento")
        line.with_user(self.user_operator).write({"quantity": validated_qty})
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            res = picking.with_user(self.user_operator).button_validate()
            if isinstance(res, dict) and res.get("res_model") == (
                "stock.backorder.confirmation"
            ):
                wizard = (
                    self.env["stock.backorder.confirmation"]
                    .with_user(self.user_operator)
                    .with_context(res["context"])
                    .create({})
                )
                wizard.with_user(self.user_operator).process()
        self.assertEqual(
            picking.state, "done", "La entrega parcial no quedó validada"
        )
        self.assertTrue(picking.backorder_ids, "No se generó backorder")
        return picking, rc.records


class TestFormAccess(SyncCommon):
    """Cubre el acceso al formulario de una transferencia intercompany
    validada para los tres perfiles de usuario, y documenta el
    comportamiento REAL (comprobado, no supuesto) de counterpart_picking_id.

    Acceso ORM directo, p. ej. `picking.counterpart_picking_id.display_name`,
    SÍ revienta con AccessError si la compañía de la contraparte no está
    activa en el selector del usuario en curso — se prueba abajo
    (test_counterpart_picking_id_orm_access_raises_with_narrow_company),
    aun cuando el usuario tiene esa compañía habilitada en company_ids (ver
    user_operator en SyncCommon): el selector activo (allowed_company_ids)
    puede ser más angosto que company_ids, y es lo que de verdad usa la
    ir.rule de stock.picking.

    La vía que usa el formulario web real, `web_read()` (ver
    `web/models/models.py` de este build), envuelve esa resolución de
    display_name en `sudo()` — así que, concretamente hoy, NO revienta por
    esa vía. Es un detalle interno de esa implementación, no documentado
    como comportamiento garantizado de la API, y no cubre otras superficies
    (reportes, otras vistas, XML-RPC, autocomplete). Por eso la vista NUNCA
    agrega counterpart_picking_id como field: usa has_counterpart_picking
    (Boolean, `bool()` puro — no dispara ninguna lectura de campos ni pasa
    por la ir.rule bajo ningún camino) para decidir si mostrar el botón
    "Contraparte".
    """

    VIEW_FIELDS = (
        "name",
        "state",
        "can_edit_done",
        "has_counterpart_picking",
        "move_ids_without_package",
        "scheduled_date",
        "priority",
    )

    def test_counterpart_picking_id_orm_access_raises_with_narrow_company(self):
        """Acceso ORM directo (no vía formulario) al Many2one revienta.

        Esto prueba el hecho ORM crudo — no el camino real del formulario
        web, que pasa por web_read() y hoy queda protegido por un sudo()
        interno de esa función (ver docstring de la clase). Es la razón por
        la que la vista nunca expone counterpart_picking_id como field: si
        algún día alguien lo agrega igual, este comportamiento de fondo
        sigue estando ahí, esperando a que cambie ese detalle interno no
        contractual de web_read.
        """
        delivery, _reception = self._create_delivery()
        self.env.invalidate_all()
        restricted = delivery.with_user(self.user_operator).with_context(
            allowed_company_ids=[self.company1.id]
        )
        with self.assertRaises(AccessError):
            restricted.counterpart_picking_id.display_name

    def test_operator_reads_form_fields_with_narrow_company(self):
        """El riesgo central: el operador (sin el rol) tiene que poder leer
        los campos reales de la vista aunque su compañía activa en el
        selector no incluya la de la contraparte."""
        delivery, _reception = self._create_delivery()
        self.env.invalidate_all()
        restricted = delivery.with_user(self.user_operator).with_context(
            allowed_company_ids=[self.company1.id]
        )
        result = restricted.web_read({f: {} for f in self.VIEW_FIELDS})
        self.assertEqual(result[0]["id"], delivery.id)
        self.assertFalse(result[0]["can_edit_done"])
        self.assertTrue(result[0]["has_counterpart_picking"])

    def test_manager_one_company_reads_form_fields(self):
        """user_manager_one (el rol, una sola compañía habilitada) también
        tiene que poder abrir el formulario sin reventar."""
        delivery, _reception = self._create_delivery()
        self.env.invalidate_all()
        restricted = delivery.with_user(self.user_manager_one).with_context(
            allowed_company_ids=[self.company1.id]
        )
        result = restricted.web_read({f: {} for f in self.VIEW_FIELDS})
        self.assertEqual(result[0]["id"], delivery.id)
        self.assertFalse(result[0]["can_edit_done"])
        self.assertTrue(result[0]["has_counterpart_picking"])

    def test_manager_both_reads_form_fields(self):
        """user_manager_both puede leer el formulario y can_edit_done da True."""
        delivery, _reception = self._create_delivery()
        self.env.invalidate_all()
        restricted = delivery.with_user(self.user_manager_both).with_context(
            allowed_company_ids=[self.company1.id, self.company2.id]
        )
        result = restricted.web_read({f: {} for f in self.VIEW_FIELDS})
        self.assertEqual(result[0]["id"], delivery.id)
        self.assertTrue(result[0]["can_edit_done"])
        self.assertTrue(result[0]["has_counterpart_picking"])

    def test_plain_picking_has_no_counterpart_flag(self):
        """Un picking sin espejo no muestra el botón: has_counterpart_picking
        da False y la lectura del formulario no cambia de comportamiento."""
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
        result = picking.with_user(self.user_operator).web_read(
            {f: {} for f in self.VIEW_FIELDS}
        )
        self.assertFalse(result[0]["has_counterpart_picking"])
        self.assertFalse(result[0]["can_edit_done"])

    def test_form_view_combined_arch_preserves_is_locked_and_full_field_read(self):
        """Guard contra reintroducir el readonly ingenuo del plan original,
        sobre el arch COMBINADO — no sobre el arch propio del record.

        Ronda de corrección 1, Minor 4: leer arch_db del propio
        view_picking_form_intercompany_edit es casi tautológico (prueba el
        texto que uno mismo escribió). get_view() fuerza a Odoo a aplicar
        TODA la herencia sobre stock.view_picking_form (incluida la de
        cualquier otro módulo instalado con mayor prioridad que pise el
        mismo atributo), así que si eso pasara, este test lo detectaría.

        De paso cierra el hueco de cobertura marcado aparte: deriva el
        field spec del arch real (no una lista hardcodeada que se olvidaba,
        por ejemplo, de is_locked) y hace el read completo como
        user_operator con la compañía activa reducida a la propia.
        """
        import re

        from lxml import etree

        view_info = (
            self.env["stock.picking"]
            .with_user(self.user_operator)
            .get_view(view_type="form")
        )
        arch = view_info["arch"]
        self.assertIn(
            "state == 'done' and is_locked and not can_edit_done", arch
        )
        self.assertIn(
            "state == 'cancel' or (state == 'done' and not can_edit_done)", arch
        )

        # Solo los fields de stock.picking en el nivel superior: los
        # anidados dentro de una sub-vista de un o2m (p. ej. las líneas de
        # move_ids_without_package) pertenecen a OTRO modelo (stock.move) y
        # no se pueden pasar tal cual a web_read() de stock.picking — de
        # ahí el filtro "not(ancestor::field)".
        root = etree.fromstring(arch.encode())
        field_names = sorted(
            {el.get("name") for el in root.xpath("//field[not(ancestor::field)]")}
        )
        self.assertIn("is_locked", field_names)
        self.assertIn("priority", field_names)
        self.assertIn("has_counterpart_picking", field_names)
        self.assertIn("can_edit_done", field_names)
        # priority no debe traer readonly propio en el arch combinado: es
        # el mismo criterio de "no restringir lo que hoy es libre" que
        # motivó no tocarlo en la vista (ver GUARDED_PICKING_FIELDS en
        # models/stock_picking.py).
        priority_tag = re.search(r'<field name="priority"[^>]*/?>', arch)
        self.assertIsNotNone(priority_tag)
        self.assertNotIn("readonly", priority_tag.group(0))

        delivery, _reception = self._create_delivery()
        self.env.invalidate_all()
        restricted = delivery.with_user(self.user_operator).with_context(
            allowed_company_ids=[self.company1.id]
        )
        result = restricted.web_read({f: {} for f in field_names})
        self.assertEqual(result[0]["id"], delivery.id)
        self.assertFalse(result[0]["can_edit_done"])
        self.assertTrue(result[0]["has_counterpart_picking"])

    def test_plain_picking_button_action_raises_user_error(self):
        """Sin contraparte, el botón (si se invoca igual) explica el porqué."""
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
        with self.assertRaisesRegex(UserError, "no tiene contraparte"):
            picking.with_user(self.user_operator).action_open_counterpart_picking()

    def test_operator_can_open_counterpart_from_narrow_company(self):
        """Reemplaza la verificación manual de UI del Step 5: clickear el
        botón "Contraparte" no debe reventar aunque la compañía activa del
        operador en el selector no incluya la de la contraparte, y el
        contexto devuelto debe activarla."""
        delivery, reception = self._create_delivery()
        self.env.invalidate_all()
        restricted = delivery.with_user(self.user_operator).with_context(
            allowed_company_ids=[self.company1.id]
        )
        action = restricted.action_open_counterpart_picking()
        self.assertEqual(action["res_model"], "stock.picking")
        self.assertEqual(action["res_id"], reception.id)
        self.assertEqual(
            action["context"]["allowed_company_ids"], [self.company2.id]
        )

    def test_manager_both_button_opens_delivery_from_reception(self):
        """El botón también funciona en el sentido inverso: desde la
        recepción hacia la entrega, para el manager con las dos compañías."""
        delivery, reception = self._create_delivery()
        action = reception.with_user(
            self.user_manager_both
        ).action_open_counterpart_picking()
        self.assertEqual(action["res_id"], delivery.id)
        self.assertEqual(
            action["context"]["allowed_company_ids"], [self.company1.id]
        )

    def test_manager_one_company_button_raises_clear_error(self):
        """Ronda de corrección 1, Important 1.

        user_manager_one tiene el rol pero SOLO company1 habilitada (ver
        SyncCommon). Antes del fix, el botón armaba igual un contexto con
        allowed_company_ids=[company2] (el sudo() en company_id no
        chequeaba que el usuario tuviera esa compañía), y el primer read
        que dispararía el cliente web contra el formulario destino
        reventaba con un AccessError crudo de Environment.companies (mismo
        caso que ya rompió la Tarea 4). Ahora tiene que fallar acá, antes,
        con un UserError explícito.
        """
        delivery, _reception = self._create_delivery()
        with self.assertRaisesRegex(UserError, "No tenés habilitada la compañía"):
            delivery.with_user(
                self.user_manager_one
            ).action_open_counterpart_picking()

    def test_button_action_strips_default_context_keys(self):
        """Ronda de corrección 1, Minor 3.

        Si el usuario llegó a este picking desde una acción con
        default_picking_type_id (u otro default_*) de ESTA compañía,
        arrastrarlo al contexto del formulario destino (activado con
        allowed_company_ids de la OTRA compañía) puede chocar con un
        mismatch de compañía apenas el usuario intente crear algo nuevo
        desde ahí. El contexto de la acción devuelta no debe traer ninguna
        clave default_*.
        """
        delivery, _reception = self._create_delivery()
        action = (
            delivery.with_user(self.user_manager_both)
            .with_context(default_picking_type_id=999999, default_priority="1")
            .action_open_counterpart_picking()
        )
        leaked_defaults = [
            key for key in action["context"] if key.startswith("default_")
        ]
        self.assertFalse(
            leaked_defaults, f"Claves default_* filtradas: {leaked_defaults}"
        )


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
        """El operador no puede tocar una entrega intercompany ya validada.

        user_operator tiene las DOS compañías habilitadas (ver setUpClass):
        lo único que le falta es el grupo, así que esta prueba cubre
        puntualmente esa rama del guard (mensaje "requiere el rol"), no la
        de compañías.
        """
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        with self.assertRaisesRegex(AccessError, "requiere el rol"):
            line.with_user(self.user_operator).write({"quantity": 5.0})

    def test_manager_with_one_company_cannot_edit(self):
        """El manager sin acceso a las dos compañías tampoco puede.

        user_manager_one tiene el grupo pero una sola compañía habilitada:
        cubre la otra rama del guard (mensaje "tener habilitadas las dos
        compañías"), distinta de la de test_operator_cannot_edit_validated.
        """
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        with self.assertRaisesRegex(
            AccessError, "tener habilitadas las dos compañías"
        ):
            line.with_user(self.user_manager_one).write({"quantity": 5.0})

    def test_manager_with_both_companies_can_edit(self):
        """El manager con las dos compañías sí puede."""
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        line.with_user(self.user_manager_both).write({"quantity": 5.0})
        self.assertEqual(line.quantity, 5.0)

    def test_operator_cannot_change_uom_of_validated_line(self):
        """Cambiar la UoM de una línea validada exige el rol.

        stock.move.line.write() no bloquea product_uom_id en done a nivel
        core (a diferencia de stock.move.product_uom, ver
        test_move_uom_change_is_blocked_by_core más abajo): reescribe
        quantity_product_uom y deshace/rehace el movimiento de quants
        real. Sin este campo en GUARDED_LINE_FIELDS, un operador podía
        convertir 10 Unidades entregadas en 10 Docenas (120 unidades
        reales) sin el rol y sin que se propague al espejo.
        """
        delivery, _reception = self._create_delivery(qty=10.0)
        line = delivery.move_line_ids[0]
        dozen = self.env.ref("uom.product_uom_dozen")
        with self.assertRaisesRegex(AccessError, "requiere el rol"):
            line.with_user(self.user_operator).write({"product_uom_id": dozen.id})

    def test_operator_cannot_change_package_or_owner_of_validated_line(self):
        """Cambiar el paquete o el propietario de una línea validada exige el rol.

        Estos dos campos están en la lista "triggers" del write() core de
        stock.move.line: para una línea done, cambiarlos deshace y rehace
        el movimiento de quants real (misma familia de riesgo que
        quantity/product_uom_id), así que cambian el contenido efectivo
        de la transferencia y deben quedar vigilados igual.
        """
        delivery, _reception = self._create_delivery()
        line = delivery.move_line_ids[0]
        package = self.env["stock.quant.package"].create({"name": "SYNC-PKG"})
        with self.assertRaisesRegex(AccessError, "requiere el rol"):
            line.with_user(self.user_operator).write({"package_id": package.id})
        partner = self.env["res.partner"].create({"name": "SYNC-OWNER"})
        with self.assertRaisesRegex(AccessError, "requiere el rol"):
            line.with_user(self.user_operator).write({"owner_id": partner.id})

    def test_operator_cannot_reparent_validated_line_to_another_move(self):
        """Mover una línea validada a otro move exige el rol.

        move_id no está en la lista "triggers" del write() core de
        move.line (no dispara undo/redo de quants por sí solo), pero
        reparentar una línea validada a otro move cambia igual qué
        transferencia contiene efectivamente qué movimiento: mismo
        criterio de "contenido efectivo" que el resto de
        GUARDED_LINE_FIELDS.

        picking_id NO se prueba acá: se sacó de GUARDED_LINE_FIELDS en la
        ronda de corrección 2 porque el propio _create_backorder() de
        Odoo lo reparenta con el picking origen ya "done" — vigilarlo
        bloqueaba toda validación parcial con backorder. Ver el comentario
        junto a GUARDED_LINE_FIELDS en models/stock_move_line.py y
        test_operator_creates_backorder_without_role más abajo.
        """
        delivery, _reception = self._create_delivery()
        other_delivery, _other_reception = self._create_delivery(
            product=self.product2
        )
        line = delivery.move_line_ids[0]
        with self.assertRaisesRegex(AccessError, "requiere el rol"):
            line.with_user(self.user_operator).write(
                {"move_id": other_delivery.move_ids[0].id}
            )

    def test_move_uom_change_is_blocked_by_core(self):
        """stock.move.product_uom no necesita guard propio: Odoo ya lo bloquea.

        `stock.move.write()` core levanta UserError incondicionalmente
        si `product_uom` está en vals y el move ya está done — corre
        antes de llegar a nuestro guard y no depende del rol del
        usuario. No hay hueco que cerrar acá; se deja documentado con
        este test para que quede registrado que se verificó, no
        asumido.
        """
        delivery, _reception = self._create_delivery()
        move = delivery.move_ids[0]
        dozen = self.env.ref("uom.product_uom_dozen")
        with self.assertRaises(UserError):
            move.with_user(self.user_manager_both).write({"product_uom": dozen.id})

    def test_can_edit_done_flag(self):
        """El campo que gobierna el readonly de la vista refleja las dos condiciones."""
        delivery, _reception = self._create_delivery()
        self.assertFalse(delivery.with_user(self.user_operator).can_edit_done)
        self.assertFalse(delivery.with_user(self.user_manager_one).can_edit_done)
        self.assertTrue(delivery.with_user(self.user_manager_both).can_edit_done)

    def test_can_edit_done_flag_with_cold_cache(self):
        """can_edit_done no debe reventar con AccessError al leerse sin caché.

        El espejo vive en la otra compañía. La ir.rule core de
        stock.picking restringe la lectura a `company_id in
        env.companies` (compañías activas en el selector; sin contexto
        explícito, cae a `user.company_ids`). Con la caché tibia (recién
        creado en la misma transacción), leer counterpart.company_id no
        dispara esa regla porque el ORM no la re-evalúa en un hit de
        caché — así que un test que solo lee en caliente no detecta el
        problema. invalidate_all() fuerza una lectura real desde la base
        y prueba la regla de verdad: sin sudo() en el compute, esto
        reventaba con AccessError en vez de devolver False para
        user_manager_one (que solo tiene una compañía habilitada, y por
        lo tanto sus `env.companies` no incluye la del espejo).
        """
        delivery, _reception = self._create_delivery()
        self.env.invalidate_all()
        self.assertFalse(delivery.with_user(self.user_manager_one).can_edit_done)
        self.env.invalidate_all()
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

    def test_operator_creates_backorder_without_role(self):
        """El operador sin rol puede validar una entrega intercompany parcial.

        Esta es la regresión Critical de la ronda de corrección 2:
        _create_backorder() de Odoo reparenta las líneas del picking
        origen al picking de backorder escribiendo picking_id con el
        origen ya "done" y el espejo intercompany ya creado. Si
        picking_id estuviera vigilado, esa escritura interna del propio
        flujo de validación de Odoo caía en el guard y el operador normal
        —quien no tiene ni necesita el rol de manager— no podía validar
        ninguna entrega intercompany parcial.
        """
        delivery, _reception = self._create_delivery_with_backorder(
            demand_qty=10.0, validated_qty=4.0
        )
        self.assertEqual(delivery.state, "done")
        self.assertTrue(delivery.backorder_ids)

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
