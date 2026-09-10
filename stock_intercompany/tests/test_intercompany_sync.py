# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

import re
from unittest.mock import patch

from odoo import Command, fields
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
        cls.product_lot = cls.env["product.product"].create(
            {
                "name": "Sync Product Lot",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": cls.env.ref("product.product_category_all").id,
            }
        )
        cls.product_lot.company_id = False
        # Ronda de corrección 1 (Tarea 10), Minor 1 (seguimiento): desde
        # que el ACL de stock.move.unlink() quedó acotado a
        # group_intercompany_manager (Important 4), un test de "operador
        # SIN el rol no puede borrar" hecho con user_operator es vacuo:
        # el AccessError que dispara es el ACL genérico de Odoo, no
        # nuestro guard -pasaría igual aunque el guard estuviera roto-.
        # Este usuario tiene permiso de unlink GENÉRICO sobre stock.move
        # (stock.group_stock_manager, "Inventory/Administrator") pero NO
        # el rol intercompany: aísla la prueba de nuestro guard del ACL
        # de base.
        cls.user_admin_no_role = cls.env["res.users"].create(
            {
                "login": "sync_admin_no_role",
                "name": "Admin Sin Rol Intercompany",
                "email": "sync_admin_no_role@example.org",
                "company_id": cls.company1.id,
                "company_ids": [
                    Command.link(cls.company1.id),
                    Command.link(cls.company2.id),
                ],
                "groups_id": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.env.ref("stock.group_stock_manager").id),
                ],
            }
        )

    def _create_reserved_delivery_picking(self, demand_qty, product, lot=None):
        """Crea una entrega intercompany CON demanda real y stock reservado.

        Compartido por _create_delivery y _create_delivery_with_backorder.
        Ronda de corrección 1, Critical 1: la versión anterior de
        _create_delivery creaba la línea directo sobre el picking, SIN un
        move con demanda (product_uom_qty). Eso dejaba al move espejo con
        product_uom_qty=0.0 -medido-, y con demanda 0 Odoo core nunca
        genera backorder, con o sin la supresión de la Tarea 7: la
        funcionalidad central de este módulo (recibir de menos ajusta la
        entrega) no se estaba ejercitando en ningún test. Acá se crea un
        stock.move real con la demanda pedida y se reserva de verdad contra
        stock disponible (action_assign), igual que ya hacía
        _create_delivery_with_backorder -que si probaba el camino real,
        pero solo para el caso parcial-.

        Corre con user_operator (sin el rol): es quien tiene que poder
        crear y confirmar una entrega intercompany en el uso diario.

        `lot` (Tarea 9): para productos con `tracking == "lot"`, core exige
        un lote en la línea para poder validar (`_action_done` revienta con
        UserError si falta). Se pasa como `lot_id` del quant reservado para
        que `action_assign` lo propague solo a la línea, igual que pasaría
        con stock real ya loteado -sin esto, ningún test de este módulo
        podría llegar a `button_validate()` con un producto trazado.
        """
        lot_record = self.env["stock.lot"].browse(lot) if lot else None
        self.env["stock.quant"].sudo()._update_available_quantity(
            product, self.stock_location, demand_qty, lot_id=lot_record
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
        return picking, line

    def _create_delivery(self, qty=10.0, product=None, lot=None):
        """Crea y valida una entrega intercompany con demanda completa.

        Devuelve (entrega, recepción). La reserva ya deja la línea en la
        cantidad total pedida (sin diferencia demanda/hecho), así que no
        debería generar backorder: se verifica explícitamente.

        `lot` (Tarea 9): se reenvía a `_create_reserved_delivery_picking`
        para poder validar productos con `tracking == "lot"` (ver el
        docstring de ese método).
        """
        product = product or self.product
        picking, line = self._create_reserved_delivery_picking(qty, product, lot=lot)
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.with_user(self.user_operator).button_validate()
        self.assertEqual(picking.state, "done", "La entrega no quedó validada")
        self.assertEqual(
            len(rc.records), 1, "Se creó más de un picking en el bloque"
        )
        self.assertFalse(
            picking.backorder_ids,
            "La entrega con demanda completa no debería generar backorder",
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

        Corre siempre con user_operator (sin el rol), porque es
        justamente el operador normal quien tiene que poder validar una
        entrega parcial sin necesitar el rol de manager.
        """
        product = product or self.product
        picking, line = self._create_reserved_delivery_picking(demand_qty, product)
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

    def _quant_qty(self, product, location):
        """Suma la cantidad de quant real (no la demanda ni la cantidad
        del move) de `product` en `location`, en sudo -las dos compañías
        de este módulo pueden no estar activas en el selector del usuario
        de test-. Ronda de corrección 1 (revisor), Minor 2: los tests de
        anulación/baja deben verificar el quant real, no solo los campos
        del move -son cosas distintas, y solo el quant prueba que el
        stock físico se revirtió de verdad-."""
        return sum(
            self.env["stock.quant"]
            .sudo()
            ._gather(product, location, strict=False)
            .mapped("quantity")
        )


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


class TestQuantitySync(SyncCommon):
    """Tarea 7: sincronización de cantidades y supresión de backorder en el espejo.

    Regla de negocio central del módulo: el operador destino recibe de menos
    y valida sin pedirle el rol; eso ajusta la entrega de origen
    automáticamente, y la recepción espejo nunca genera backorder (si lo
    hiciera, quedarían dos recepciones para una sola entrega).
    """

    def test_demand_propagates_delivery_to_reception(self):
        """La demanda editada en la entrega viaja a la recepción."""
        delivery, reception = self._create_delivery(qty=10.0)
        delivery.move_ids[0].with_user(self.user_manager_both).write(
            {"product_uom_qty": 8.0}
        )
        self.assertEqual(reception.move_ids[0].product_uom_qty, 8.0)

    def test_done_quantity_propagates_reception_to_delivery(self):
        """La cantidad hecha editada en la recepción viaja a la entrega."""
        delivery, reception = self._create_delivery(qty=10.0)
        reception.move_line_ids[0].with_user(self.user_manager_both).write(
            {"quantity": 7.0}
        )
        self.assertEqual(delivery.move_line_ids[0].quantity, 7.0)

    def test_operator_partial_receipt_adjusts_delivery(self):
        """El operador recibe 9 de 10 y la entrega queda en 9, sin pedirle el rol."""
        delivery, reception = self._create_delivery(qty=10.0)
        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})
        reception.button_validate()
        self.assertEqual(reception.state, "done")
        self.assertEqual(delivery.move_line_ids[0].quantity, 9.0)

    def test_partial_receipt_creates_no_backorder(self):
        """La recepción espejo nunca genera backorder.

        Ronda de corrección 2: sin el `assertEqual(reception.state, "done")`
        este test pasaba vacuamente si se revertían las dos supresiones
        (button_validate + _action_done) — sin supresión, el flujo se
        frena en el wizard de backorder, nunca se llega a crear un
        backorder, y `assertFalse(backorders)` da verdadero igual, sin
        haber probado nada. Verificado revirtiendo ambas supresiones: con
        el `assertEqual` de abajo, el test SÍ falla (`reception.state` se
        queda en un estado no-"done" porque `button_validate()` devuelve
        la acción del wizard en vez de completar la validación).
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})
        reception.button_validate()
        self.assertEqual(reception.state, "done")
        backorders = self.env["stock.picking"].sudo().search(
            [("backorder_id", "=", reception.id)]
        )
        self.assertFalse(backorders)

    def test_quantity_sync_notes_posted_on_both_sides(self):
        """El ajuste de cantidad deja nota propia en las dos puntas, SIEMPRE.

        Se cuenta message_ids en las dos puntas en vez de grepear el texto
        del body: la base corre en es_AR y cualquier fragmento en inglés
        vuelve la aserción vacua (ya pasó en la Tarea 6).

        Ronda de corrección 2: la ronda anterior suprimía la nota propia
        del lado `done` para no convivir con el mensaje nativo de core
        ("The done move line has been corrected."). Esa instrucción del
        coordinador estaba equivocada y se revirtió: el spec exige nota
        propia en las DOS puntas siempre -es la mitigación de que un
        operador de otra compañía, sin rol, esté tocando stock ya
        validado de la compañía origen, y el mensaje de core no nombra ni
        el picking contraparte ni la compañía-. Lo que sí se conserva de
        la ronda anterior es la precisión: nada de `assertGreater`. Se
        assertea el conteo EXACTO en las dos puntas, usando
        `_quantity_change_logged_by_core` (ahora solo un helper de
        predicción, no de supresión) para saber si además hay que contar
        el mensaje nativo de core en cada lado.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        delivery_line = delivery.move_line_ids[0]
        reception_line = reception.move_line_ids[0]
        expected_delivery = 1 + (
            1 if delivery_line._quantity_change_logged_by_core() else 0
        )
        expected_reception = 1 + (
            1 if reception_line._quantity_change_logged_by_core() else 0
        )
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        reception_line.with_user(self.user_manager_both).write({"quantity": 7.0})
        self.assertEqual(
            len(delivery.message_ids),
            before_delivery + expected_delivery,
            "La entrega debería recibir la nota propia siempre, más la de "
            f"core si le toca; mensajes: {delivery.message_ids.mapped('body')}",
        )
        self.assertEqual(
            len(reception.message_ids),
            before_reception + expected_reception,
            "La recepción debería recibir la nota propia siempre, más la "
            f"de core si le toca; mensajes: {reception.message_ids.mapped('body')}",
        )
        # Con demanda completa (_create_delivery), la entrega SIEMPRE está
        # done -es el caso normal del spec- y la recepción todavía no: si
        # esto deja de sostenerse, el desglose de arriba deja de probar lo
        # que dice.
        self.assertEqual(expected_delivery, 2, "La entrega debería estar done acá")
        self.assertEqual(
            expected_reception, 1, "La recepción no debería estar done acá"
        )

    def test_no_infinite_echo_line_write_call_count(self):
        """La propagación de cantidad no rebota: exactamente 2 write() reales.

        Mismo criterio que el análogo de cabecera (Tarea 6): sin el corte de
        is_propagation(), esto entraría en recursión infinita.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        model_class = type(self.env["stock.move.line"])
        original_write = model_class.write
        calls = []

        def counting_write(self, vals):
            calls.append(self.ids)
            return original_write(self, vals)

        with patch.object(model_class, "write", counting_write):
            reception.move_line_ids[0].with_user(self.user_manager_both).write(
                {"quantity": 7.0}
            )

        self.assertEqual(
            len(calls),
            2,
            "Se esperaban exactamente 2 llamadas a write() (origen + "
            f"espejo); se registraron {len(calls)}: {calls}",
        )

    def test_core_internal_writes_during_validation_do_not_echo(self):
        """Las escrituras internas de core durante la validación (picked,
        date en move lines, state/date en moves) no deben disparar
        propagación ni notas espurias del lado de la recepción.

        Inmune al reloj: no depende de que las escrituras internas caigan en
        el mismo segundo que la del operador, a diferencia del bug análogo
        de la Tarea 6 con scheduled_date.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})
        after_write_delivery = len(delivery.message_ids)
        after_write_reception = len(reception.message_ids)
        reception.button_validate()
        self.assertEqual(reception.state, "done")
        # La única propagación real es la del write() explícito de arriba;
        # button_validate() no debe agregar notas nuevas de sync.
        self.assertEqual(len(delivery.message_ids), after_write_delivery)
        self.assertEqual(len(reception.message_ids), after_write_reception)
        self.assertGreater(after_write_delivery, before_delivery)
        self.assertGreater(after_write_reception, before_reception)

    def test_plain_picking_backorder_not_suppressed(self):
        """Un picking sin contraparte conserva el comportamiento original:
        validar de menos sigue generando backorder.

        La supresión de backorder del Step 5 tiene que alcanzar solo a los
        pickings con espejo intercompany; este test demuestra que uno sin
        espejo no cambia de comportamiento.
        """
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
        self.env["stock.quant"].sudo()._update_available_quantity(
            self.product, self.stock_location, 10.0
        )
        self.env["stock.move"].with_user(self.user_operator).create(
            {
                "name": self.product.name,
                "product_id": self.product.id,
                "product_uom_qty": 10.0,
                "product_uom": self.uom_unit.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "picking_id": picking.id,
            }
        )
        picking.with_user(self.user_operator).action_confirm()
        picking.with_user(self.user_operator).action_assign()
        line = picking.move_line_ids
        line.with_user(self.user_operator).write({"quantity": 4.0})
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
        self.assertEqual(picking.state, "done")
        self.assertTrue(
            picking.backorder_ids,
            "Un picking sin espejo intercompany debe seguir generando "
            "backorder normalmente",
        )

    def test_no_backorder_even_with_create_backorder_always(self):
        """La supresión no depende de picking_ids_not_to_backorder: aguanta
        aunque el tipo de operación de la recepción esté en "Always".

        Ronda de corrección 1, Critical 2. Core
        (stock/models/stock_picking.py, button_validate) filtra
        `picking_ids_not_to_backorder` con `lambda p:
        p.picking_type_id.create_backorder != 'always'`: con esa política
        -un valor soportado de fábrica- el espejo se caía de la lista de
        supresión y generaba backorder igual, medido antes del fix:
        `ALWAYS2 state=done bo=['Sync /IN/00002']`. El fix fuerza
        `cancel_backorder=True` directamente en `_action_done()` para
        cualquier picking con `counterpart_of_picking_id` propio, sin
        pasar por esa lista.
        """
        self.picking_type_in.create_backorder = "always"
        delivery, reception = self._create_delivery(qty=10.0)
        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})
        reception.button_validate()
        self.assertEqual(reception.state, "done")
        backorders = self.env["stock.picking"].sudo().search(
            [("backorder_id", "=", reception.id)]
        )
        self.assertFalse(
            backorders,
            "La recepción espejo no debe generar backorder ni con "
            "create_backorder='always' en su tipo de operación",
        )
        self.assertEqual(delivery.move_line_ids[0].quantity, 9.0)

    def test_mixed_batch_does_not_steal_wizard_from_plain_picking(self):
        """Validar un espejo junto con un picking suelto en el mismo batch
        no le roba a este último su wizard de backorder.

        Ronda de corrección 1, Important 3. Antes, `button_validate()`
        aplicaba `skip_backorder=True` a `self` entero -no solo a los
        pickings con espejo-, así que `_pre_action_done_hook()` (core) no
        corría `_check_backorder()` para NINGÚN picking del batch: el
        picking sin contraparte perdía en silencio su pregunta y quedaba
        con un backorder creado sin que nadie lo confirmara. Medido antes
        del fix: `MIXED res=True plain_state=done backorders=[...]` (sin
        wizard). Caminos reales que arman un batch así: la acción de
        servidor de la vista lista (`stock.action_validate_picking`) y
        `stock.picking.batch.action_done()`.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.env["stock.quant"].sudo()._update_available_quantity(
            self.product2, self.stock_location, 10.0
        )
        plain = (
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
        self.env["stock.move"].with_user(self.user_operator).create(
            {
                "name": self.product2.name,
                "product_id": self.product2.id,
                "product_uom_qty": 10.0,
                "product_uom": self.uom_unit.id,
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "picking_id": plain.id,
            }
        )
        plain.with_user(self.user_operator).action_confirm()
        plain.with_user(self.user_operator).action_assign()
        plain.move_line_ids.with_user(self.user_operator).write({"quantity": 4.0})

        reception = reception.with_user(self.user_operator)
        reception.move_line_ids[0].write({"quantity": 9.0})

        batch = reception | plain
        res = batch.button_validate()
        self.assertTrue(
            isinstance(res, dict)
            and res.get("res_model") == "stock.backorder.confirmation",
            f"Se esperaba el wizard de backorder para el picking sin "
            f"espejo dentro del batch mixto; res={res}",
        )
        self.assertEqual(
            reception.state,
            "done",
            "El espejo, dentro del mismo batch, se valida solo sin wizard",
        )
        mirror_backorders = self.env["stock.picking"].sudo().search(
            [("backorder_id", "=", reception.id)]
        )
        self.assertFalse(
            mirror_backorders,
            "El espejo no debe generar backorder ni en un batch mixto",
        )

        wizard = (
            self.env["stock.backorder.confirmation"]
            .with_user(self.user_operator)
            .with_context(res["context"])
            .create({})
        )
        wizard.with_user(self.user_operator).process()
        self.assertEqual(plain.state, "done")
        self.assertTrue(
            plain.backorder_ids,
            "El picking sin espejo, una vez confirmado el wizard, sí debe "
            "generar su propio backorder",
        )


class TestHeaderSync(SyncCommon):
    """Tarea 6: sincronización de cabecera (fecha programada y prioridad).

    Patrón que copian las tareas 7 (cantidades) y 10 (líneas): un cambio de
    cabecera en cualquiera de las dos puntas se propaga a la otra en un solo
    salto, deja nota en el chatter de las dos, y nunca toca un picking sin
    contraparte.
    """

    # NOTA DE ALCANCE (ronda de corrección 1): la entrega intercompany
    # SIEMPRE está "done" en cuanto tiene contraparte -el espejo se crea
    # justo al validarla, en _create_counterpart_picking()-, y un picking
    # origen "done" no propaga nada (ver el docstring de
    # _propagate_picking_changes). Por eso todos los tests de este archivo
    # que ejercitan una propagación REAL escriben sobre la RECEPCIÓN, no
    # sobre la entrega: es la única dirección viva. Ver
    # test_scheduled_date_never_propagates_because_delivery_is_always_done
    # más abajo, que documenta y verifica explícitamente la consecuencia
    # para "scheduled_date": bajo esta regla, no hay ningún escenario
    # donde de verdad propague.

    def test_priority_propagates_from_reception(self):
        """La propagación de cabecera va de la recepción hacia la entrega.

        Es la única dirección viva (ver nota de alcance arriba): la
        recepción no está done recién creada, la entrega sí.
        """
        delivery, reception = self._create_delivery()
        reception.with_user(self.user_manager_both).write({"priority": "1"})
        self.assertEqual(delivery.priority, "1")

    def test_scheduled_date_never_propagates_because_delivery_is_always_done(self):
        """Documenta la consecuencia real de la regla nueva para scheduled_date.

        `scheduled_date` no se propaga hacia un picking done/cancel
        (SYNC_BLOCKED_STATES). La entrega, del lado que fuera que se mire,
        siempre está done en cuanto existe el espejo: si se escribe desde
        la recepción (la única punta no-done), el destino (la entrega) ya
        está done y la propagación se corta ahí. Si se intenta escribir
        directo sobre la entrega, el propio inverse de Odoo
        (`_set_scheduled_date`) revienta con UserError antes de llegar
        siquiera a nuestro código, porque la entrega ya está done.

        No hay, bajo esta regla, ningún escenario de este módulo donde
        `scheduled_date` propague de verdad. Se deja este test para
        dejarlo verificado y documentado en vez de asumido: si algún día
        cambia (por ejemplo, si una tarea futura agrega un tercer estado
        de picking intercompany que no sea done), este test tiene que
        empezar a fallar y avisar.
        """
        delivery, reception = self._create_delivery()
        before_delivery_msgs = len(delivery.message_ids)
        before_reception_msgs = len(reception.message_ids)
        original_delivery_date = delivery.scheduled_date
        new_date = "2030-01-15 10:00:00"
        reception.with_user(self.user_manager_both).write(
            {"scheduled_date": new_date}
        )
        self.assertEqual(
            fields.Datetime.to_string(reception.scheduled_date), new_date,
            "La propia recepción sí debe aceptar el cambio (no está done)",
        )
        self.assertEqual(
            delivery.scheduled_date, original_delivery_date,
            "La entrega (siempre done) no debe recibir el cambio propagado",
        )
        self.assertEqual(len(delivery.message_ids), before_delivery_msgs)
        self.assertEqual(len(reception.message_ids), before_reception_msgs)
        with self.assertRaises(UserError):
            delivery.with_user(self.user_manager_both).write(
                {"scheduled_date": new_date}
            )

    def test_no_infinite_echo_write_call_count(self):
        """La propagación no rebota: cuenta las llamadas reales a write().

        Escribir sobre la recepción (única dirección viva) tiene que
        producir EXACTAMENTE dos invocaciones de write() sobre
        stock.picking: la del usuario y la propagada hacia la entrega. Si
        el guard de is_propagation() no cortara el eco, esto entraría en
        recursión infinita (RecursionError) o, en el mejor de los casos,
        contaría de más.

        Lo que NO garantiza: que no haya, en otro escenario, una cadena
        más larga de propagaciones legítimas encadenadas entre sí; solo
        cubre el caso puntual de esta escritura.
        """
        delivery, reception = self._create_delivery()
        model_class = type(self.env["stock.picking"])
        original_write = model_class.write
        calls = []

        def counting_write(self, vals):
            calls.append(self.ids)
            return original_write(self, vals)

        with patch.object(model_class, "write", counting_write):
            reception.with_user(self.user_manager_both).write({"priority": "1"})

        self.assertEqual(
            len(calls),
            2,
            "Se esperaban exactamente 2 llamadas a write() (origen + "
            f"espejo); se registraron {len(calls)}: {calls}",
        )
        self.assertEqual(reception.priority, "1")
        self.assertEqual(delivery.priority, "1")

    def test_writing_same_value_does_not_propagate_or_note(self):
        """Reescribir el mismo valor no debe propagar ni postear nota.

        Sobre la recepción (única dirección viva), reescribir su propio
        valor de "priority" no debe disparar una segunda write() sobre
        la entrega ni ruido en ningún chatter.
        """
        delivery, reception = self._create_delivery()
        before_delivery_msgs = len(delivery.message_ids)
        before_reception_msgs = len(reception.message_ids)
        model_class = type(self.env["stock.picking"])
        original_write = model_class.write
        calls = []

        def counting_write(self, vals):
            calls.append(self.ids)
            return original_write(self, vals)

        with patch.object(model_class, "write", counting_write):
            reception.with_user(self.user_manager_both).write(
                {"priority": reception.priority}
            )

        self.assertEqual(
            len(calls),
            1,
            "Reescribir el mismo valor no debe disparar una segunda "
            f"write() sobre el espejo; se registraron {len(calls)}: {calls}",
        )
        self.assertEqual(len(delivery.message_ids), before_delivery_msgs)
        self.assertEqual(len(reception.message_ids), before_reception_msgs)

    def test_no_counterpart_does_not_propagate_or_note(self):
        """Un picking sin contraparte no dispara propagación ni nota.

        Es la restricción global del plan: ninguna de las dos cosas debe
        ocurrir sobre un picking sin espejo.
        """
        picking = (
            self.env["stock.picking"]
            .with_user(self.user_manager_both)
            .create(
                {
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        before_msgs = len(picking.message_ids)
        picking.write({"priority": "1", "scheduled_date": fields.Datetime.now()})
        self.assertEqual(picking.priority, "1")
        self.assertEqual(len(picking.message_ids), before_msgs)

    def test_note_posted_on_both_sides(self):
        """El cambio deja nota en las dos puntas, y la de destino nombra el origen."""
        delivery, reception = self._create_delivery()
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        reception.with_user(self.user_manager_both).write({"priority": "1"})
        self.assertGreater(len(delivery.message_ids), before_delivery)
        self.assertGreater(len(reception.message_ids), before_reception)
        delivery_note = delivery.message_ids.filtered(
            lambda m: reception.name in (m.body or "")
        )
        self.assertTrue(
            delivery_note,
            "No se encontró en la entrega ninguna nota que nombre el "
            "picking de origen",
        )

    def test_action_done_does_not_echo_priority_reset(self):
        """El reset interno de priority='0' que hace _action_done() no debe
        propagarse como si fuera una edición real.

        Reproduce el bug reportado en la ronda de corrección 1: se crea
        una entrega con priority='1' (antes de validar), se valida (Odoo
        internamente hace `self.write({'date_done': ..., 'priority': '0'})`
        sobre la entrega YA done y con el espejo YA creado -ver el
        comentario junto a GUARDED_PICKING_FIELDS-), y se verifica que la
        recepción conserva el priority original de la creación, sin nota
        espuria de "Priority: 1 → 0". Es inmune al reloj: no depende de
        que creación y validación caigan en segundos distintos (a
        diferencia del bug análogo con scheduled_date, que sí era
        dependiente del reloj y que la regla nueva ya cierra sin
        necesidad de un test específico: ver
        test_scheduled_date_never_propagates_because_delivery_is_always_done).
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
                    "priority": "1",
                }
            )
        )
        self.env["stock.move.line"].create(
            {
                "location_id": self.stock_location.id,
                "location_dest_id": self.custs_location.id,
                "product_id": self.product.id,
                "product_uom_id": self.uom_unit.id,
                "quantity": 5.0,
                "picking_id": picking.id,
            }
        )
        with RecordCapturer(self.env["stock.picking"], []) as rc:
            picking.action_confirm()
            picking.button_validate()
        self.assertEqual(picking.state, "done")
        self.assertEqual(len(rc.records), 1, "Se creó más de un picking en el bloque")
        reception = rc.records
        self.assertEqual(
            picking.priority, "0",
            "El propio Odoo resetea priority a '0' al validar",
        )
        self.assertEqual(
            reception.priority, "1",
            "El espejo se creó con el priority ORIGINAL (antes del reset "
            "interno); el reset posterior no debe pisarlo vía propagación",
        )
        spurious = reception.message_ids.filtered(
            lambda m: "riority" in (m.body or "")
        )
        self.assertFalse(
            spurious,
            f"Nota espuria de prioridad en la recepción: {spurious.mapped('body')}",
        )

    def test_batch_write_touching_both_sides_does_not_duplicate(self):
        """Un write() que toca las dos puntas a la vez no duplica la propagación.

        Reproducido antes de este fix: `(delivery | reception).write(...)`
        generaba 3 llamadas a write() y +2 notas espurias en cada picking,
        porque cada picking del batch intentaba además propagar hacia el
        otro, que ya había recibido el valor directo del propio batch.
        Ahora se salta la propagación cuando la contraparte también está
        en `self`.
        """
        delivery, reception = self._create_delivery()
        before_delivery_msgs = len(delivery.message_ids)
        before_reception_msgs = len(reception.message_ids)
        model_class = type(self.env["stock.picking"])
        original_write = model_class.write
        calls = []

        def counting_write(self, vals):
            calls.append(self.ids)
            return original_write(self, vals)

        with patch.object(model_class, "write", counting_write):
            (delivery | reception).with_user(self.user_manager_both).write(
                {"priority": "1"}
            )

        self.assertEqual(
            len(calls),
            1,
            "Un write() que ya toca las dos puntas no debe generar ninguna "
            f"llamada extra de propagación; se registraron {len(calls)}: {calls}",
        )
        self.assertEqual(delivery.priority, "1")
        self.assertEqual(reception.priority, "1")
        self.assertEqual(len(delivery.message_ids), before_delivery_msgs)
        self.assertEqual(len(reception.message_ids), before_reception_msgs)


class TestLineAddition(SyncCommon):
    def test_new_line_on_validated_picking_mirrors_and_moves_stock(self):
        """Agregar un producto a una entrega validada lo replica y mueve stock.

        `_create_delivery` valida la entrega, pero la recepción espejo
        queda "assigned" (lista, sin validar): es la contraparte quien
        decide cuándo procesarla, como en el resto de la suite
        (`test_operator_partial_receipt_adjusts_delivery` y análogos
        validan la recepción a mano antes de asertar `state == "done"`).
        El escenario de esta tarea es "las dos puntas YA validadas", así
        que hay que llevar la recepción a done acá también.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).button_validate()
        self.assertEqual(reception.state, "done")
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        new_move = delivery.move_ids.filtered(
            lambda m: m.product_id == self.product2
        )
        self.assertEqual(len(new_move), 1)
        self.assertEqual(new_move.state, "done")
        self.assertEqual(new_move.quantity, 4.0)

        mirrored = reception.move_ids.filtered(
            lambda m: m.product_id == self.product2
        )
        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored.counterpart_of_move_id, new_move)
        self.assertEqual(mirrored.product_uom_qty, 4.0)
        self.assertEqual(mirrored.state, "done")
        self.assertEqual(mirrored.move_line_ids.picking_id, reception)

        # El estado "done" del move no alcanza para probar que el stock se
        # movió de verdad: se verifica el quant en las dos compañías.
        # product2 no tenía stock previo en la ubicación de origen de la
        # entrega, así que el quant queda negativo -es exactamente lo
        # esperado de una edición forzada de cantidad sobre un move ya
        # done, no una limitación del test-.
        Quant = self.env["stock.quant"].sudo()
        origin_qty = Quant._get_available_quantity(
            self.product2, delivery.location_id, allow_negative=True
        )
        self.assertEqual(origin_qty, -4.0)
        dest_qty = Quant._get_available_quantity(
            self.product2, reception.location_dest_id
        )
        self.assertEqual(dest_qty, 4.0)

    def test_addition_posts_note_on_both_sides(self):
        """El alta deja nota en las dos puntas, con conteo exacto de mensajes."""
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).button_validate()
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        self.assertEqual(len(delivery.message_ids), before_delivery + 1)
        self.assertEqual(len(reception.message_ids), before_reception + 1)

    def test_operator_cannot_add_line_to_validated(self):
        """El operador no puede agregar productos a un picking validado."""
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaises(AccessError):
            self.env["stock.move"].with_user(self.user_operator).create(
                {
                    "picking_id": delivery.id,
                    "product_id": self.product2.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": delivery.location_id.id,
                    "location_dest_id": delivery.location_dest_id.id,
                    "name": self.product2.name,
                }
            )

    def test_new_line_without_counterpart_picking_unaffected(self):
        """Un picking sin contraparte no cambia de comportamiento al agregar líneas."""
        picking = (
            self.env["stock.picking"]
            .with_user(self.user_operator)
            .with_context(default_company_id=self.company1.id)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        move = self.env["stock.move"].with_user(self.user_operator).create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 3.0,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "name": self.product.name,
            }
        )
        self.assertEqual(move.state, "draft")
        self.assertFalse(move.counterpart_of_move_id)

    def test_addition_does_not_trigger_spurious_counterpart_on_mirror_creation(self):
        """Crear el espejo original no debe disparar una segunda ronda de create().

        La Tarea 7 tuvo un caso análogo: un write() del propio flujo de
        validación pisaba el origen porque no distinguía "edición real" de
        "bootstrap interno". Acá se verifica que armar la entrega y su
        recepción espejo (que en el proceso crea moves con picking_id
        apuntando a un picking con counterpart_picking_id ya resuelto) no
        produzca un tercer move (un "espejo del espejo").
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertEqual(len(delivery.move_ids), 1)
        self.assertEqual(len(reception.move_ids), 1)
        self.assertFalse(delivery.move_ids.counterpart_of_move_id)
        self.assertEqual(reception.move_ids.counterpart_of_move_id, delivery.move_ids)

    def test_new_line_with_pending_reception_completes_on_later_validate(self):
        """Rama de producción normal: la recepción sigue `assigned` cuando se
        agrega la línea (nadie la validó todavía), y se termina de procesar
        después con un `button_validate()` común.

        Ronda de corrección 1, "cosas chicas" 1: los otros dos tests de
        alta fuerzan la recepción a `done` antes de agregar la línea para
        cubrir el escenario "las dos puntas ya validadas", pero el caso
        que se da SIEMPRE en producción (`_create_delivery` deja la
        recepción `assigned`, sin validar) no tenía cobertura propia.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertNotEqual(reception.state, "done")
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        new_move = delivery.move_ids.filtered(
            lambda m: m.product_id == self.product2
        )
        self.assertEqual(new_move.state, "done")

        mirrored = reception.move_ids.filtered(
            lambda m: m.product_id == self.product2
        )
        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored.counterpart_of_move_id, new_move)
        self.assertNotEqual(
            mirrored.state,
            "done",
            "Sin validar la recepción a mano, el espejo no debería llegar "
            "solo a done",
        )

        reception.with_user(self.user_operator).button_validate()
        self.assertEqual(reception.state, "done")
        self.assertEqual(mirrored.state, "done")
        self.assertEqual(mirrored.quantity, 4.0)

    def test_manager_one_company_cannot_add_line_to_validated(self):
        """El manager con el rol pero una sola compañía habilitada tampoco puede.

        Segunda rama del mensaje de `_check_intercompany_edit_allowed`: a
        diferencia de `test_operator_cannot_add_line_to_validated` (sin
        rol), `user_manager_one` sí tiene el rol pero le falta la
        compañía de la contraparte habilitada.

        Ronda de corrección 2 (revisor), hallazgo del mismo patrón fuera
        del alcance pedido (TestLineRemoval) pero encontrado al barrer el
        módulo: con `assertRaises(AccessError)` pelado, neutralizar
        `_check_intercompany_edit_allowed` con un `return` temprano NO
        hacía fallar este test -otro `AccessError` completamente ajeno
        (ir.rule de compañía, al intentar crear el espejo en
        company2 sin tenerla habilitada) lo tapaba-. Se usa
        `assertRaisesRegex` contra el `display_name` de la entrega para
        que el test solo pase con el AccessError de nuestro guard.
        """
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaisesRegex(AccessError, re.escape(delivery.display_name)):
            self.env["stock.move"].with_user(self.user_manager_one).create(
                {
                    "picking_id": delivery.id,
                    "product_id": self.product2.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": delivery.location_id.id,
                    "location_dest_id": delivery.location_dest_id.id,
                    "name": self.product2.name,
                }
            )

    def test_operator_cannot_add_line_to_cancelled_counterpart(self):
        """Ronda de corrección 1, Important 1: un picking cancelado con
        contraparte no se puede "resucitar" agregándole una línea sin rol.

        Reproducido antes del fix: sin extender
        `_check_intercompany_edit_allowed` a `state == "cancel"`, esta
        creación no tiraba `AccessError` y la recepción pasaba de
        `cancel` a `draft` sola (el `_compute_state` de core prioriza
        `any_draft` sobre `all_cancel`).
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).action_cancel()
        self.assertEqual(reception.state, "cancel")
        with self.assertRaises(AccessError):
            self.env["stock.move"].with_user(self.user_operator).create(
                {
                    "picking_id": reception.id,
                    "product_id": self.product2.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": reception.location_id.id,
                    "location_dest_id": reception.location_dest_id.id,
                    "name": self.product2.name,
                }
            )
        self.assertEqual(
            reception.state,
            "cancel",
            "La recepción cancelada no debe resucitar aunque el AccessError "
            "se capture",
        )

    def test_manager_cannot_add_line_to_cancelled_counterpart(self):
        """Ni el manager con las dos compañías puede resucitar un picking
        cancelado agregándole una línea: pasa el chequeo de rol, pero se
        rechaza igual con `UserError` porque "editar" no significa
        "reabrir un documento cancelado".
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).action_cancel()
        self.assertEqual(reception.state, "cancel")
        with self.assertRaises(UserError):
            self.env["stock.move"].with_user(self.user_manager_both).create(
                {
                    "picking_id": reception.id,
                    "product_id": self.product2.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": reception.location_id.id,
                    "location_dest_id": reception.location_dest_id.id,
                    "name": self.product2.name,
                }
            )
        self.assertEqual(reception.state, "cancel")

    def test_addition_on_done_delivery_with_cancelled_counterpart_raises(self):
        """Ronda de corrección 1, Important 2: agregar una línea sobre una
        entrega `done` cuyo espejo está `cancel` no debe dejar las dos
        puntas divergentes.

        Reproducido antes del fix: el move de origen quedaba `done` (con
        stock y SVL movidos en la compañía A) mientras la recepción
        pasaba de `cancel` a `assigned` con la línea vieja todavía
        `cancel` — el invariante central de la tarea (mover stock en las
        dos puntas) fallaba en silencio.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).action_cancel()
        self.assertEqual(reception.state, "cancel")
        with self.assertRaises(UserError):
            self.env["stock.move"].with_user(self.user_manager_both).create(
                {
                    "picking_id": delivery.id,
                    "product_id": self.product2.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": delivery.location_id.id,
                    "location_dest_id": delivery.location_dest_id.id,
                    "name": self.product2.name,
                }
            )
        self.assertEqual(
            reception.state,
            "cancel",
            "La recepción cancelada no debe resucitar por el intento "
            "fallido de alta",
        )
        self.assertFalse(
            reception.move_ids.filtered(lambda m: m.product_id == self.product2),
            "No debe quedar ninguna línea fantasma en la recepción cancelada",
        )

    def test_new_line_requires_lot_for_tracked_product(self):
        """Ronda de corrección 1, Important 3: un producto con seguimiento
        por lote no puede pasar a `done` sin lote.

        Reproducido antes del fix: como el move nace `done` directo desde
        `super().create()` (core, porque el picking ya está `done`),
        `_action_done()` lo filtra y nunca corre
        `stock.move.line._action_done()` -que es donde vive el chequeo
        obligatorio de lote de core-, así que el alta pasaba sin lote,
        silenciosamente.
        """
        tracked = self.env["product.product"].create(
            {
                "name": "Sync Tracked Product",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": self.env.ref("product.product_category_all").id,
            }
        )
        tracked.company_id = False
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).button_validate()
        with self.assertRaises(UserError):
            self.env["stock.move"].with_user(self.user_manager_both).create(
                {
                    "picking_id": delivery.id,
                    "product_id": tracked.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": delivery.location_id.id,
                    "location_dest_id": delivery.location_dest_id.id,
                    "name": tracked.name,
                }
            )

    def test_new_line_with_lot_replicates_lot_to_counterpart(self):
        """Con el lote indicado explícitamente, el alta de un producto
        trazado sí se replica, con el lote equivalente en la otra
        compañía (`map_lot`, hasta ahora inalcanzable por este camino)."""
        tracked = self.env["product.product"].create(
            {
                "name": "Sync Tracked Product 2",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": self.env.ref("product.product_category_all").id,
            }
        )
        tracked.company_id = False
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).button_validate()
        lot = (
            self.env["stock.lot"]
            .with_company(self.company1)
            .create(
                {
                    "name": "LOT-TASK8-001",
                    "product_id": tracked.id,
                    "company_id": self.company1.id,
                }
            )
        )
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": tracked.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": tracked.name,
                "move_line_ids": [
                    Command.create(
                        {
                            "picking_id": delivery.id,
                            "product_id": tracked.id,
                            "product_uom_id": self.uom_unit.id,
                            "quantity": 4.0,
                            "lot_id": lot.id,
                            "location_id": delivery.location_id.id,
                            "location_dest_id": delivery.location_dest_id.id,
                        }
                    )
                ],
            }
        )
        new_move = delivery.move_ids.filtered(lambda m: m.product_id == tracked)
        self.assertEqual(new_move.state, "done")
        self.assertEqual(new_move.move_line_ids.lot_id.name, "LOT-TASK8-001")

        mirrored = reception.move_ids.filtered(lambda m: m.product_id == tracked)
        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored.state, "done")
        self.assertEqual(mirrored.move_line_ids.lot_id.name, "LOT-TASK8-001")
        self.assertNotEqual(
            mirrored.move_line_ids.lot_id, new_move.move_line_ids.lot_id
        )
        self.assertEqual(mirrored.move_line_ids.lot_id.company_id, self.company2)


class TestLotSync(SyncCommon):
    """Sync del lote elegido en una línea existente hacia el espejo.

    Distinto de `test_new_line_with_lot_replicates_lot_to_counterpart`
    (Tarea 8, en `TestLineAddition`): ese cubre el ALTA de una línea nueva
    con lote sobre un picking ya done, vía
    `stock.move._create_counterpart_move` (stock_move.py). Acá se cubren
    dos caminos distintos, los dos en `stock_picking.py`: la construcción
    inicial del espejo con lote ya puesto en la línea de origen
    (`_get_counterpart_move_commands`, ejercitado en `_create_lot_delivery`
    antes de cualquier `write`) y el WRITE de `lot_id` sobre una línea ya
    existente de la entrega ya validada, vía el bucle de propagación de
    `stock.move.line.write()`.
    """

    def _create_lot_delivery(self, qty=5.0):
        """Crea y valida una entrega de `product_lot` con un lote inicial.

        `product_lot` tiene `tracking == "lot"`: core exige un lote en la
        línea para poder validar (ver el docstring de
        `_create_reserved_delivery_picking`), así que hace falta reservar
        contra un quant ya loteado antes de poder llegar a
        `button_validate()` con demanda completa. El lote inicial es
        distinto del que después escribe cada test, para que ese write sea
        un cambio real -no un no-op- que ejercite el mapeo del Step 3.

        Ronda de corrección 1 (Tarea 9), Important 3: el revisor mostró que
        revirtiendo SOLO el mapeo de `_get_counterpart_move_commands`
        (Step 4) los dos tests de esta clase seguían en verde, porque el
        `write` posterior (Step 3) pisa el lote de la línea espejo y tapa
        cualquier agujero de la creación. Se assertea acá, ANTES de que
        cualquier test llegue a escribir nada, que el espejo ya nace con el
        lote equivalente -así el Step 4 queda cubierto de verdad, no solo
        de encuentro-.
        """
        initial_lot = self.env["stock.lot"].create(
            {
                "name": "LOTE-INICIAL",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        delivery, reception = self._create_delivery(
            qty=qty, product=self.product_lot, lot=initial_lot.id
        )
        mirror_lot = reception.move_line_ids[0].lot_id
        self.assertTrue(mirror_lot, "El espejo debería nacer con un lote mapeado")
        self.assertEqual(mirror_lot.name, "LOTE-INICIAL")
        self.assertEqual(mirror_lot.company_id, self.company2)
        return delivery, reception

    def test_lot_mapped_to_destination_company(self):
        """El lote de la entrega se resuelve como lote propio de la otra compañía."""
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOTE-001",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        delivery, reception = self._create_lot_delivery(qty=5.0)
        delivery.move_line_ids[0].with_user(self.user_manager_both).write(
            {"lot_id": lot_a.id}
        )
        mirrored_lot = reception.move_line_ids[0].lot_id
        self.assertTrue(mirrored_lot)
        self.assertEqual(mirrored_lot.name, "LOTE-001")
        self.assertEqual(mirrored_lot.company_id, self.company2)
        self.assertNotEqual(mirrored_lot, lot_a)

    def test_existing_lot_is_reused(self):
        """Si el lote ya existe en la compañía destino, no se duplica."""
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOTE-002",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        lot_b = self.env["stock.lot"].create(
            {
                "name": "LOTE-002",
                "product_id": self.product_lot.id,
                "company_id": self.company2.id,
            }
        )
        delivery, reception = self._create_lot_delivery(qty=5.0)
        delivery.move_line_ids[0].with_user(self.user_manager_both).write(
            {"lot_id": lot_a.id}
        )
        self.assertEqual(reception.move_line_ids[0].lot_id, lot_b)

    def test_lot_change_notes_posted_on_both_sides(self):
        """El cambio de lote en una línea validada deja nota propia en las
        dos puntas, con conteo EXACTO (Ronda de corrección 1, Critical 2).

        Antes del fix, `post_sync_note` solo se llamaba si `"quantity" in
        changed`: un `write({"lot_id": ...})` puro cambiaba stock ya
        validado de la otra compañía sin dejar ningún rastro en ninguna de
        las dos puntas.

        Se cuenta `message_ids` en vez de grepear el body (la base corre en
        es_AR). `_quantity_change_logged_by_core` -pese al nombre, ver su
        docstring- audita cualquier campo de `triggers` (core,
        stock_move_line.py: `location_id`, `lot_id`, etc., no solo
        `quantity`) sobre una línea `done` y almacenable, así que también
        predice la nota nativa de core para este cambio de lote.
        """
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOTE-003",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        delivery, reception = self._create_lot_delivery(qty=5.0)
        delivery_line = delivery.move_line_ids[0]
        reception_line = reception.move_line_ids[0]
        expected_delivery = 1 + (
            1 if delivery_line._quantity_change_logged_by_core() else 0
        )
        expected_reception = 1 + (
            1 if reception_line._quantity_change_logged_by_core() else 0
        )
        before_delivery = len(delivery.message_ids)
        before_reception = len(reception.message_ids)
        delivery_line.with_user(self.user_manager_both).write({"lot_id": lot_a.id})
        self.assertEqual(
            len(delivery.message_ids),
            before_delivery + expected_delivery,
            "La entrega debería recibir la nota propia siempre, más la de "
            f"core si le toca; mensajes: {delivery.message_ids.mapped('body')}",
        )
        self.assertEqual(
            len(reception.message_ids),
            before_reception + expected_reception,
            "La recepción debería recibir la nota propia siempre, más la "
            f"de core si le toca; mensajes: {reception.message_ids.mapped('body')}",
        )
        # La entrega SIEMPRE está done (_create_lot_delivery la valida) y la
        # recepción todavía no: si esto deja de sostenerse, el desglose de
        # arriba deja de probar lo que dice.
        self.assertEqual(expected_delivery, 2, "La entrega debería estar done acá")
        self.assertEqual(
            expected_reception, 1, "La recepción no debería estar done acá"
        )

    def test_lot_without_company_is_reused_as_is(self):
        """Un lote sin `company_id` ya sirve en cualquier compañía: no se
        duplica ni revienta (Ronda de corrección 1, Critical 1).

        Reproduce el camino real de la UI: los productos intercompany son
        compartidos (`company_id = False`), así que `stock.lot
        ._compute_company_id` (core) deja el lote SIN compañía apenas se lo
        crea sin pasarla explícita -a diferencia del resto de los tests de
        esta clase, que sí la pasan a propósito para simular un lote ya
        existente y loteado por compañía-. Antes del fix, `map_lot` no
        contemplaba `company_id = False`: la búsqueda por
        `company_id = company.id` no encontraba nada y el intento de crear
        un lote nuevo con el mismo nombre y producto chocaba con
        `_check_unique_lot` (core), que sí cruza los lotes sin compañía, y
        tiraba `ValidationError` -bloqueando la validación de cualquier
        entrega intercompany con un lote recién creado por el flujo normal-.
        """
        lot_sin_compania = self.env["stock.lot"].create(
            {
                "name": "LOTE-SIN-COMPANIA",
                "product_id": self.product_lot.id,
            }
        )
        self.assertFalse(
            lot_sin_compania.company_id,
            "El lote debería nacer sin compañía, como lo deja la UI sobre "
            "un producto intercompany compartido",
        )
        delivery, reception = self._create_lot_delivery(qty=5.0)
        delivery.move_line_ids[0].with_user(self.user_manager_both).write(
            {"lot_id": lot_sin_compania.id}
        )
        self.assertEqual(reception.move_line_ids[0].lot_id, lot_sin_compania)

    def test_lot_rewrite_same_lot_does_not_echo(self):
        """Reescribir el MISMO lote (ya mapeado) no debe forzar un write()
        extra sobre el espejo (Ronda de corrección 1, Minor 1).

        `line.lot_id` (compañía de origen) y `counterpart.lot_id` (compañía
        destino) son SIEMPRE registros distintos aunque representen "el
        mismo" lote -son de compañías diferentes-, así que comparar esos
        dos directamente daba siempre verdadero y forzaba una propagación
        incluso sin cambio real: undo/redo de quants sobre una recepción ya
        validada, más una nota espuria de core sin ningún cambio que la
        explique. Se compara el lote YA MAPEADO (`map_lot(line.lot_id,
        counterpart.company_id)`) contra `counterpart.lot_id` en cambio.
        """
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOTE-004",
                "product_id": self.product_lot.id,
                "company_id": self.company1.id,
            }
        )
        delivery, reception = self._create_lot_delivery(qty=5.0)
        line = delivery.move_line_ids[0]
        line.with_user(self.user_manager_both).write({"lot_id": lot_a.id})
        model_class = type(self.env["stock.move.line"])
        original_write = model_class.write
        calls = []

        def counting_write(self, vals):
            calls.append(self.ids)
            return original_write(self, vals)

        with patch.object(model_class, "write", counting_write):
            line.with_user(self.user_manager_both).write({"lot_id": lot_a.id})

        self.assertEqual(
            len(calls),
            1,
            "Reescribir el mismo lote (sin cambio real tras el mapeo) no "
            f"debería propagar hacia el espejo; llamadas: {calls}",
        )


class TestLineRemoval(SyncCommon):
    """Tarea 10: baja de líneas.

    En un picking sin validar, borrar una línea es un unlink real. En uno
    validado, un move en `done` no se puede borrar sin perder la
    trazabilidad del movimiento original: "eliminar" pasa a significar
    demanda y cantidad hecha en cero (`action_intercompany_void`), con la
    línea visible en cero como registro histórico -consecuencia conocida
    y aceptada del diseño, no un defecto-.

    NOTA DE ALCANCE (verificada contra el código real, no asumida): una
    entrega intercompany está SIEMPRE `done` en cuanto tiene contraparte
    -el espejo se crea recién en `_action_done()`- así que la línea de
    ORIGEN de una entrega nunca puede recibir un unlink real: la propia
    entrega siempre fuerza la rama de anulación. El unlink real de
    verdad solo es alcanzable del lado de la RECEPCIÓN (que puede quedar
    `assigned`, sin validar, mucho después de que su contraparte ya esté
    `done`) o cuando ninguna de las dos puntas está `done` todavía (una
    entrega recién creada, sin validar, sin espejo). Por eso
    `test_unlink_on_draft_removes_both_sides` no es simétrico: el lado
    que se borra desaparece de verdad, pero como su contraparte (la
    entrega) siempre está `done`, esa contraparte se ANULA -no se
    borra-, con nota que lo dice explícitamente. Es la consecuencia
    real de la regla del spec, no una limitación de este test.
    """

    def test_unlink_on_draft_removes_own_side_and_voids_done_counterpart(self):
        """Borrar una línea de una recepción sin validar la borra ahí, y
        anula (no borra) su contraparte, que ya está done -incluido el
        quant real, no solo los campos del move (ronda de corrección 1,
        Minor 2)."""
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertNotEqual(reception.state, "done")
        move = reception.move_ids[0]
        counterpart = move._get_counterpart_move()
        self.assertTrue(counterpart)
        self.assertEqual(counterpart.picking_id, delivery)
        self.assertEqual(delivery.state, "done")
        origin_qty_before = self._quant_qty(
            counterpart.product_id, counterpart.location_id
        )
        move.with_user(self.user_manager_both).unlink()
        self.assertFalse(move.exists(), "La línea de la recepción debe borrarse de verdad")
        self.assertTrue(
            counterpart.exists(),
            "La línea de la entrega (ya done) no debe borrarse, solo anularse",
        )
        self.assertEqual(counterpart.quantity, 0.0)
        self.assertEqual(counterpart.product_uom_qty, 0.0)
        origin_qty_after = self._quant_qty(
            counterpart.product_id, counterpart.location_id
        )
        self.assertEqual(
            origin_qty_after,
            origin_qty_before + 10.0,
            "El quant de origen de la entrega debe recuperar las 10 "
            "unidades que la anulación revierte",
        )

    def test_unlink_both_sides_undone_removes_both(self):
        """Cuando NINGUNA de las dos puntas está validada, el unlink borra
        de verdad en las dos: caso de una línea agregada a una entrega
        todavía sin validar, sin contraparte creada por este módulo -se
        arma el vínculo a mano para poder ejercitar ese caso, ya que el
        módulo nunca lo genera solo (ver nota de alcance de la clase)."""
        picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_operator)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        other_picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_operator)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        # El corte barato de unlink() resuelve la relación a nivel
        # PICKING antes de mirar los moves (ver el docstring de
        # unlink()): sin vincular también los pickings acá, "relevant"
        # queda vacío y el test no ejercitaría nada.
        other_picking.counterpart_of_picking_id = picking.id
        move = self.env["stock.move"].with_user(self.user_operator).create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 3.0,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "name": self.product.name,
            }
        )
        mirror = self.env["stock.move"].with_user(self.user_operator).create(
            {
                "picking_id": other_picking.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 3.0,
                "location_id": other_picking.location_id.id,
                "location_dest_id": other_picking.location_dest_id.id,
                "name": self.product.name,
                "counterpart_of_move_id": move.id,
            }
        )
        self.assertEqual(picking.state, "draft")
        self.assertEqual(other_picking.state, "draft")
        # Se borra desde `mirror` (el lado marcado como espejo,
        # `counterpart_of_picking_id` propio): es el lado que el corte
        # barato de unlink() puede resolver sin buscar, ya que `picking`
        # (el origen) no sabe que tiene un espejo sin pagar el search que
        # el corte evita fuera del estado "done" -ver el docstring de
        # unlink()-.
        mirror.with_user(self.user_manager_both).unlink()
        self.assertFalse(move.exists())
        self.assertFalse(mirror.exists())

    def test_void_on_validated_zeroes_both_sides(self):
        """En un picking validado, anular deja la línea en cero en las dos
        puntas, con el quant real revertido en las dos compañías (ronda de
        corrección 1, Minor 2: no alcanza con mirar los campos del move)."""
        delivery, reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        mirrored = move._get_counterpart_move()
        origin_qty_before = self._quant_qty(move.product_id, move.location_id)
        dest_qty_before = self._quant_qty(
            mirrored.product_id, mirrored.location_dest_id
        )
        move.with_user(self.user_manager_both).action_intercompany_void()
        self.assertTrue(move.exists())
        self.assertEqual(move.quantity, 0.0)
        self.assertEqual(move.product_uom_qty, 0.0)
        self.assertEqual(mirrored.quantity, 0.0)
        self.assertEqual(mirrored.product_uom_qty, 0.0)
        origin_qty_after = self._quant_qty(move.product_id, move.location_id)
        dest_qty_after = self._quant_qty(
            mirrored.product_id, mirrored.location_dest_id
        )
        self.assertEqual(
            origin_qty_after,
            origin_qty_before + 10.0,
            "El quant de origen (entrega) debe recuperar las 10 unidades",
        )
        # La recepción nunca llegó a `done` (_create_delivery la deja
        # `assigned`): su move_line nunca movió un quant real de destino
        # -eso solo pasa cuando la línea está `done`-, así que anularla
        # (quantity 10 -> 0, sobre una línea todavía no `done`) no debe
        # cambiar ningún quant ahí. Solo la punta que SÍ estaba `done`
        # (la entrega) tiene un quant real que revertir.
        self.assertEqual(
            dest_qty_after,
            dest_qty_before,
            "El quant de destino (recepción, nunca done) no debe cambiar",
        )

    def test_unlink_on_validated_voids_instead(self):
        """Borrar una línea de un picking validado la anula en vez de
        borrarla, revirtiendo el quant real de origen (ronda de
        corrección 1, Minor 2)."""
        delivery, _reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        origin_qty_before = self._quant_qty(move.product_id, move.location_id)
        move.with_user(self.user_manager_both).unlink()
        self.assertTrue(move.exists())
        self.assertEqual(move.quantity, 0.0)
        self.assertEqual(move.product_uom_qty, 0.0)
        origin_qty_after = self._quant_qty(move.product_id, move.location_id)
        self.assertEqual(origin_qty_after, origin_qty_before + 10.0)

    def test_operator_cannot_remove_from_validated(self):
        """Un usuario sin el rol intercompany no puede anular líneas de un
        picking validado.

        Ronda de corrección 1, Minor 1 (seguimiento): se usa
        `user_admin_no_role` -tiene permiso de unlink GENÉRICO sobre
        stock.move, pero no el rol intercompany- en vez de
        `user_operator` -que directamente no puede invocar `unlink()`
        por el ACL de base desde Important 4-, para que el AccessError
        que se comprueba sea el de NUESTRO guard, no el ACL genérico.

        Ronda de corrección 2 (revisor), hallazgo repetido del módulo:
        `assertRaises(AccessError)` pelado no discrimina QUÉ AccessError
        se disparó. El re-revisor neutralizó `_check_intercompany_edit_allowed`
        con un `return` temprano y este test seguía en verde -otro
        `AccessError` completamente ajeno lo tapaba: revertir un move
        `done` dispara valuación contable, y `user_admin_no_role` no
        tiene acceso de lectura a `account.move` ("Journal Entry"), así
        que el `unlink()` igual reventaba con AccessError aunque nuestro
        guard estuviera apagado. Se usa `assertRaisesRegex` contra el
        `display_name` del picking -que el guard interpola en su mensaje,
        y ningún otro AccessError de este camino podría mencionar-, para
        que el test solo pase si el AccessError es el nuestro.
        """
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaisesRegex(AccessError, re.escape(delivery.display_name)):
            delivery.move_ids[0].with_user(self.user_admin_no_role).unlink()

    def test_operator_cannot_void_directly(self):
        """El operador tampoco puede invocar action_intercompany_void
        directo. Ver la nota de `test_operator_cannot_remove_from_validated`
        sobre por qué `assertRaisesRegex` y no `assertRaises` pelado."""
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaisesRegex(AccessError, re.escape(delivery.display_name)):
            delivery.move_ids[0].with_user(
                self.user_operator
            ).action_intercompany_void()

    def test_manager_one_company_cannot_remove_from_validated(self):
        """El manager con el rol pero una sola compañía tampoco puede. Ver
        la nota de `test_operator_cannot_remove_from_validated` sobre por
        qué `assertRaisesRegex` y no `assertRaises` pelado."""
        delivery, _reception = self._create_delivery(qty=10.0)
        with self.assertRaisesRegex(AccessError, re.escape(delivery.display_name)):
            delivery.move_ids[0].with_user(self.user_manager_one).unlink()

    def test_operator_cannot_delete_undone_line_whose_counterpart_is_done(self):
        """Ronda de corrección propia: el chequeo de rol de unlink() debe
        mirar también el estado de la CONTRAPARTE, no solo el del propio
        picking. Sin esto, un usuario sin el rol intercompany podía
        anular (vía cascada) stock ya validado de la otra compañía con
        solo borrar una línea pendiente de su lado -la recepción, sin
        validar, no pasaba por el guard, y la anulación de la entrega
        done ocurría sin control-.

        Se usa `user_admin_no_role` (ver su docstring en setUpClass) en
        vez de `user_operator` para que el AccessError sea el de nuestro
        guard, no el ACL genérico de stock.move.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertNotEqual(reception.state, "done")
        move = reception.move_ids[0]
        with self.assertRaises(AccessError):
            move.with_user(self.user_admin_no_role).unlink()
        self.assertTrue(move.exists(), "No debe haberse borrado nada tras el AccessError")
        self.assertEqual(
            delivery.move_ids[0].quantity,
            10.0,
            "La entrega, todavía sin tocar, no debe haberse anulado",
        )

    def test_operator_cannot_void_undone_line_whose_counterpart_is_done(self):
        """Ronda de corrección 1 (revisor), Critical 1: el mismo agujero
        bilateral que se cerró en `unlink()` estaba abierto en
        `action_intercompany_void()` -la puerta pública que `unlink()`
        termina usando-. Reproducido por el revisor: un usuario con SOLO
        `stock.group_stock_user` (sin `group_intercompany_manager`)
        invocaba `action_intercompany_void()` directo sobre una línea de
        recepción `assigned` (su propio picking no está done/cancel, así
        que un chequeo de una sola punta lo dejaba pasar) cuya
        contraparte -la entrega- ya está `done`, y revertía stock real ya
        validado de la otra compañía sin autorización
        (`cp: quantity 30.0 -> 0.0`, en su corrida).
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertNotEqual(reception.state, "done")
        move = reception.move_ids[0]
        counterpart = move._get_counterpart_move()
        self.assertEqual(counterpart.picking_id, delivery)
        self.assertEqual(delivery.state, "done")
        origin_qty_before = self._quant_qty(
            counterpart.product_id, counterpart.location_id
        )
        with self.assertRaises(AccessError):
            move.with_user(self.user_operator).action_intercompany_void()
        self.assertEqual(
            counterpart.quantity,
            10.0,
            "La entrega, ya validada, no debe haberse anulado",
        )
        self.assertEqual(
            self._quant_qty(counterpart.product_id, counterpart.location_id),
            origin_qty_before,
            "El quant de origen de la entrega no debe haberse tocado",
        )

    def test_deleting_cancelled_mirror_picking_does_not_void_done_counterpart(self):
        """Ronda de corrección 1 (revisor), Critical 2: borrar el picking
        espejo entero (no una línea suelta) no debe cascadear ninguna
        anulación hacia la contraparte.

        Core, `stock.picking.unlink()` (stock/models/stock_picking.py),
        hace `self.move_ids.unlink()` con TODOS los moves del picking a
        la vez, como parte de la limpieza administrativa rutinaria de
        borrar una recepción cancelada. Antes de este fix, esa limpieza
        -que un manager puede hacer sin intención de tocar la otra
        compañía- cascadeaba una anulación real (revertía quants) sobre
        la entrega YA VALIDADA. Reproducido por el revisor:
        `mirror C1/IN/00001 (cancel) unlink -> cp 36.0/36.0 -> 0.0/0.0 ;
        quant origen 0 -> 36.0`.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).action_cancel()
        self.assertEqual(reception.state, "cancel")
        move = delivery.move_ids[0]
        origin_qty_before = self._quant_qty(move.product_id, move.location_id)
        before_delivery_msgs = len(delivery.message_ids)
        reception.with_user(self.user_manager_both).unlink()
        self.assertFalse(reception.exists())
        self.assertEqual(
            move.quantity,
            10.0,
            "La entrega, ya validada, no debe haberse anulado por borrar "
            "el picking espejo cancelado",
        )
        self.assertEqual(move.product_uom_qty, 10.0)
        self.assertEqual(
            self._quant_qty(move.product_id, move.location_id),
            origin_qty_before,
            "El quant de origen de la entrega no debe haberse tocado",
        )
        # Review final, Important 3: la entrega recibe UNA sola nota, la de
        # desvinculación -antes no recibía ninguna, y esa era justamente la
        # falla: el espejo desaparecía y con él el guard de la entrega
        # validada, en silencio-. Lo que sigue prohibido es la nota de
        # anulación de línea ("Línea anulada"), que sería la cascada.
        new_msgs = delivery.message_ids[
            : len(delivery.message_ids) - before_delivery_msgs
        ]
        self.assertEqual(
            len(new_msgs),
            1,
            "La entrega debe recibir exactamente la nota de desvinculación",
        )
        self.assertIn("vínculo intercompany", new_msgs.body)
        self.assertNotIn("anulada", new_msgs.body)

    def test_unlink_covers_cancel_state_via_inverse_link(self):
        """Ronda de corrección 1 (revisor), Minor 3: el corte barato de
        `unlink()` también resuelve un picking `cancel` que tiene
        contraparte solo por el vínculo INVERSO (`counterpart_of_picking_id`
        vacío en él mismo, pero otro picking le apunta) -antes solo
        cubría `state == "done"` o ser el espejo directo-.

        Poco alcanzable en el flujo real de este módulo -una entrega con
        contraparte real nunca llega a `cancel` porque core no permite
        cancelar un picking `done`- pero es exactamente el `cancel` que
        el guard de `unlink()` pretende cubrir explícitamente (ver su
        docstring), así que se arma el vínculo a mano para ejercitarlo,
        igual que ya hace `test_unlink_both_sides_undone_removes_both`
        para el caso bilateral sin validar.
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
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        move = self.env["stock.move"].with_user(self.user_operator).create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 3.0,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "name": self.product.name,
            }
        )
        picking.with_user(self.user_operator).action_cancel()
        self.assertEqual(picking.state, "cancel")
        other_picking = (
            self.env["stock.picking"]
            .with_context(default_company_id=self.company1.id)
            .with_user(self.user_operator)
            .create(
                {
                    "partner_id": self.company2.partner_id.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        # Vínculo INVERSO: other_picking apunta a picking, no al revés
        # -picking.counterpart_of_picking_id sigue vacío, exactamente el
        # caso que el corte barato debía dejar de saltear-.
        other_picking.counterpart_of_picking_id = picking.id
        # user_admin_no_role (no user_operator): tiene permiso de unlink
        # genérico sobre stock.move pero no el rol intercompany, así que
        # el AccessError es el de nuestro guard, no el ACL de base.
        with self.assertRaises(AccessError):
            move.with_user(self.user_admin_no_role).unlink()
        self.assertTrue(
            move.exists(), "No debe haberse borrado nada tras el AccessError"
        )

    def test_plain_picking_unlink_unaffected(self):
        """Un picking sin contraparte no cambia de comportamiento al borrar
        líneas: nuestro guard/cascada no se dispara para nada.

        Ronda de corrección 1 (revisor), Minor 1: el `unlink()` se hace
        con `user_manager_both`, NO porque nuestro guard exija el rol acá
        -un picking sin contraparte nunca lo exige, es justo lo que este
        test prueba-, sino porque `stock.group_stock_user` NO tiene
        `perm_unlink` sobre `stock.move` en el propio ACL base de Odoo
        (`stock/security/ir.model.access.csv`): es una restricción global
        de Inventario, ajena a este módulo, y desde la ronda de
        corrección 1 el ensanche de ACL de este módulo quedó acotado a
        `group_intercompany_manager` (antes daba unlink a TODO
        `group_stock_user` de la base, ensanche que el revisor marcó como
        no mínimo). Con `user_operator` acá, el `AccessError` genérico de
        ACL disparaba ANTES de que este test pudiera probar nada sobre
        nuestra lógica -el bug real que motivó este comentario-.
        """
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
        move = self.env["stock.move"].with_user(self.user_operator).create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 3.0,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "name": self.product.name,
            }
        )
        before_msgs = len(picking.message_ids)
        move.with_user(self.user_manager_both).unlink()
        self.assertFalse(move.exists())
        self.assertEqual(
            len(picking.message_ids),
            before_msgs,
            "Un picking sin contraparte no debe recibir ninguna nota de sync",
        )

    def test_unlink_without_counterpart_does_not_search_for_one(self):
        """El picking sin contraparte no debe pagar ningún search al borrar
        una línea: get_counterpart (el helper que hace el search) no debe
        ni siquiera invocarse. Mismo motivo que el test anterior para usar
        `user_manager_both`: es el ACL base de Odoo, no nuestro guard."""
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
        move = self.env["stock.move"].with_user(self.user_operator).create(
            {
                "picking_id": picking.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 3.0,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "name": self.product.name,
            }
        )
        with patch(
            "odoo.addons.stock_intercompany.models.stock_move.get_counterpart"
        ) as mock_get_counterpart:
            move.with_user(self.user_manager_both).unlink()
        mock_get_counterpart.assert_not_called()

    def test_removal_notes_posted_on_both_sides_draft_case(self):
        """La baja real deja nota propia en el lado borrado, y una nota de
        anulación (con atribución) en el lado que, por estar done, se
        anula en cascada en vez de borrarse.

        Se cuenta message_ids en las dos puntas con conteo exacto -nunca
        se grepea el body: la base corre en es_AR (ver el resto de la
        suite, p. ej. test_quantity_sync_notes_posted_on_both_sides)-.

        La cascada hacia la contraparte (`as_propagation`) hace la
        mutación directo -`move_line_ids.write()`/`move.write()` con
        `skip_intercompany_sync` ya activo-, sin pasar por el camino de
        `action_intercompany_void()` ni por el diff/nota propia de
        `stock.move.line.write()` (que se corta temprano con
        `is_propagation()`): por eso la contraparte NO recibe una nota
        propia de "cantidad X → Y" además de la de "Línea anulada" -daría
        una nota redundante-, aunque sí recibe la nota nativa de core
        ("The done move line has been corrected.") porque esa la postea
        el propio core en `stock.move.line.write()`, fuera de nuestro
        control.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        move = reception.move_ids[0]
        counterpart = move._get_counterpart_move()
        counterpart_line = counterpart.move_line_ids[0]
        before_reception = len(reception.message_ids)
        before_delivery = len(delivery.message_ids)
        expected_delivery = 1 + (  # "Línea anulada" (nuestra)
            1 if counterpart_line._quantity_change_logged_by_core() else 0
        )  # nota nativa de core, si corresponde
        expected_reception = 1  # "Línea eliminada" (la línea ya no existe del otro lado)
        move.with_user(self.user_manager_both).unlink()
        self.assertFalse(move.exists())
        self.assertEqual(
            len(reception.message_ids),
            before_reception + expected_reception,
            f"Mensajes reales: {reception.message_ids.mapped('body')}",
        )
        self.assertEqual(
            len(delivery.message_ids),
            before_delivery + expected_delivery,
            f"Mensajes reales: {delivery.message_ids.mapped('body')}",
        )
        void_note = delivery.message_ids.filtered(
            lambda m: reception.name in (m.body or "")
        )
        self.assertTrue(
            void_note,
            "La nota de anulación en la entrega debe nombrar el picking de "
            "origen (la recepción)",
        )

    def test_no_self_triggering_deletion_on_move_merge(self):
        """Core puede fusionar (y borrar) moves internamente al confirmar
        -stock.move._merge_moves(), vía _action_confirm(merge=True)-.
        Verificado en el fuente (stock/models/stock_move.py) que ese
        camino es el único que hace stock.move.unlink() fuera de este
        módulo sobre moves con contraparte; se reproduce acá agregando
        DOS líneas del MISMO producto a una entrega ya validada mientras
        la recepción todavía está sin validar -el escenario donde el
        espejo recién creado de la segunda línea es candidato a fusionarse
        con el de la primera, ambas en un estado elegible para
        _merge_moves (ni done, ni cancel, ni draft)-. Si esa fusión
        interna disparara nuestro unlink() como si fuera una baja real, se
        vería una nota espuria de "Línea eliminada"/"Línea anulada" además
        de las esperadas por el alta; se comprueba que NO aparece
        ninguna.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertNotEqual(reception.state, "done")
        before_reception = len(reception.message_ids)
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 4.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        self.env["stock.move"].with_user(self.user_manager_both).create(
            {
                "picking_id": delivery.id,
                "product_id": self.product2.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 5.0,
                "location_id": delivery.location_id.id,
                "location_dest_id": delivery.location_dest_id.id,
                "name": self.product2.name,
            }
        )
        mirrored = reception.move_ids.filtered(lambda m: m.product_id == self.product2)
        self.assertTrue(mirrored, "Debería haber al menos un espejo de product2")
        total_qty = sum(mirrored.mapped("product_uom_qty"))
        self.assertEqual(
            total_qty, 9.0, "La demanda total del espejo debe conservarse (4 + 5)"
        )
        # Confirma que la fusión interna de core REALMENTE ocurrió (si no,
        # el resto del test no estaría probando el escenario que dice
        # probar): los dos espejos de product2 -mismo producto, mismas
        # ubicaciones, mismo picking- son candidatos de _merge_moves y
        # terminan colapsados en un solo move.
        self.assertEqual(
            len(mirrored),
            1,
            "Se esperaba que core fusionara los dos espejos de product2 en uno",
        )
        # Conteo exacto, no grep de body (la base corre en es_AR): cada
        # alta posta exactamente 1 nota propia en la recepción (2 en
        # total), más la nota NATIVA de core sobre la fusión ("The
        # initial demand has been updated.", ajena a este módulo). Si la
        # fusión interna disparara nuestro unlink() como si fuera una
        # baja real, se sumaría una CUARTA nota de baja/anulación que no
        # corresponde a ninguna alta ni a la fusión.
        self.assertEqual(
            len(reception.message_ids),
            before_reception + 3,
            f"Mensajes reales: {reception.message_ids.mapped('body')}",
        )

    def test_no_self_triggering_deletion_on_move_merge_in_normal_context(self):
        """Ronda de corrección 1 (revisor), Important 3: el test anterior
        solo cubre la fusión DENTRO de una llamada `as_propagation(...)`
        (el alta de una línea nueva sobre una entrega ya done, que crea
        el espejo con ese flag activo) -el camino trivialmente seguro,
        porque el contexto ya viene con `skip_intercompany_sync`-. El
        revisor reprodujo la fusión en contexto NORMAL, sin pasar por
        ningún `as_propagation`: agregar una línea del mismo producto
        DIRECTO en la recepción (no vía la entrega) y correr
        `action_confirm()` a mano. En su corrida, la nota espuria fue
        "Línea eliminada" en la recepción; además, la línea que
        sobrevivió a la fusión fue la que tenía contraparte -si el orden
        interno de `groupby` de core cayera al revés, el síntoma deja de
        ser una nota espuria y pasa a ser la cascada real de Critical 2
        (anular la entrega done). Este test no depende de saber cuál
        sobrevive: verifica que, sea cual sea, no hay nota espuria Y que
        la entrega (contraparte real) no se tocó.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertNotEqual(reception.state, "done")
        original_move = reception.move_ids[0]
        self.assertTrue(original_move.counterpart_of_move_id)
        delivery_move = original_move._get_counterpart_move()
        self.assertEqual(delivery_move.picking_id, delivery)
        before_reception = len(reception.message_ids)
        before_delivery = len(delivery.message_ids)
        origin_qty_before = self._quant_qty(
            delivery_move.product_id, delivery_move.location_id
        )
        duplicate = self.env["stock.move"].with_user(
            self.user_manager_both
        ).with_company(self.company2).create(
            {
                "picking_id": reception.id,
                "product_id": self.product.id,
                "product_uom": self.uom_unit.id,
                "product_uom_qty": 10.0,
                "location_id": reception.location_id.id,
                "location_dest_id": reception.location_dest_id.id,
                "name": self.product.name,
                # Tiene que coincidir en TODOS los "distinct fields" de
                # `_prepare_merge_moves_distinct_fields()` con el move
                # original para que core los reconozca como
                # fusionables -sin esto, quedan como dos moves
                # separados y el test no ejercita la fusión que dice
                # ejercitar-.
                "description_picking": self.product.name,
            }
        )
        self.assertEqual(duplicate.state, "draft")
        self.assertFalse(
            duplicate.counterpart_of_move_id,
            "El duplicado se crea directo, sin pasar por ningún camino "
            "as_propagation de este módulo",
        )
        reception.with_user(self.user_manager_both).with_company(
            self.company2
        ).action_confirm()
        merged = reception.move_ids.filtered(lambda m: m.product_id == self.product)
        self.assertEqual(
            len(merged),
            1,
            "Se esperaba que core fusionara el duplicado con el move original",
        )
        # La entrega (contraparte real, done) no debe haberse anulado ni
        # tocado, sea cual sea el move que haya sobrevivido a la fusión.
        self.assertEqual(delivery_move.quantity, 10.0)
        self.assertEqual(delivery_move.product_uom_qty, 10.0)
        self.assertEqual(
            self._quant_qty(delivery_move.product_id, delivery_move.location_id),
            origin_qty_before,
        )
        self.assertEqual(
            len(delivery.message_ids),
            before_delivery,
            f"Mensajes reales: {delivery.message_ids.mapped('body')}",
        )
        # +1: la nota NATIVA de core sobre la fusión misma ("The initial
        # demand has been updated.", ajena a este módulo -mismo patrón que
        # test_no_self_triggering_deletion_on_move_merge-). Ninguna nota
        # NUESTRA ("Línea eliminada"/"Línea anulada") debe aparecer.
        self.assertEqual(
            len(reception.message_ids),
            before_reception + 1,
            f"Mensajes reales: {reception.message_ids.mapped('body')}",
        )


class TestFinalReviewFixes(SyncCommon):
    """Review final de rama: correcciones que ninguna revisión individual
    de tarea podía ver, porque nacen de la interacción entre piezas
    revisadas por separado (el flag de contexto y el guard, el guard y el
    ciclo de vida del picking espejo, la propagación y el chatter)."""

    def test_context_flag_alone_does_not_bypass_guard(self):
        """Critical 1: `skip_intercompany_sync` en el contexto no alcanza.

        El contexto es dato del cliente en cualquier `execute_kw`: sin el
        `env.su` en el guard, un `stock.group_stock_user` sin el rol
        editaba una entrega VALIDADA mandando el flag en el contexto
        (reproducido en la base de calidad: demanda 24 → 25), y encima sin
        propagar nada al espejo, porque el mismo flag corta la
        propagación: bypass del rol más divergencia silenciosa.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        with self.assertRaises(AccessError) as capture:
            move.with_user(self.user_operator).with_context(
                skip_intercompany_sync=True
            ).write({"product_uom_qty": 11.0})
        self.assertIn("Intercompany", str(capture.exception))
        self.assertEqual(move.product_uom_qty, 10.0)
        self.assertEqual(reception.move_ids[0].product_uom_qty, 10.0)

    def test_context_flag_alone_does_not_bypass_line_guard(self):
        """Critical 1, misma puerta desde `stock.move.line`."""
        delivery, _reception = self._create_delivery(qty=10.0)
        line = delivery.move_line_ids[0]
        with self.assertRaises(AccessError) as capture:
            line.with_user(self.user_operator).with_context(
                skip_intercompany_sync=True
            ).write({"quantity": 3.0})
        # El AccessError tiene que ser el NUESTRO: sin este chequeo el test
        # es vacuo. Verificado revirtiendo el fix hunk por hunk -sin el
        # `env.su` en el guard, la escritura igual revienta con un
        # AccessError, pero ajeno (la valorización de la línea `done` toca
        # account.move, para el que el operador no tiene permiso), y el
        # test pasaba con el agujero abierto.
        self.assertIn("Intercompany", str(capture.exception))
        self.assertEqual(line.quantity, 10.0)

    def test_context_flag_alone_does_not_bypass_unlink(self):
        """Critical 1, tercera puerta: la rama de propagación de
        `stock.move.unlink()` anula stock real (demanda y cantidad a cero)
        de un picking `done`. Si esa anulación se hiciera en sudo, el flag
        de contexto seguiría alcanzando para revertir stock validado de la
        otra compañía sin el rol; sin sudo, el guard la alcanza."""
        delivery, _reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        qty_before = self._quant_qty(move.product_id, move.location_id)
        with self.assertRaises(AccessError) as capture:
            move.with_user(self.user_admin_no_role).with_context(
                skip_intercompany_sync=True
            ).unlink()
        self.assertIn("Intercompany", str(capture.exception))
        self.assertEqual(move.product_uom_qty, 10.0)
        self.assertEqual(
            self._quant_qty(move.product_id, move.location_id), qty_before
        )

    def test_line_create_on_validated_requires_role(self):
        """Critical 2: `stock.move.line.create()` no tenía guard.

        Core mueve los quants DENTRO del propio `create()` cuando la línea
        nace `state == 'done'` (lo hereda del move), así que crear una
        línea sobre un move de un picking validado sacaba stock real sin
        pasar por ningún `write()`. Reproducido con un usuario sin el rol
        sobre una entrega validada de la base de calidad: línea creada en
        `done` y quant de origen 220 → 217.
        """
        delivery, _reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        qty_before = self._quant_qty(move.product_id, move.location_id)
        with self.assertRaises(AccessError) as capture:
            self.env["stock.move.line"].with_user(self.user_operator).create(
                {
                    "move_id": move.id,
                    "picking_id": delivery.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "quantity": 3.0,
                    "picked": True,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "company_id": delivery.company_id.id,
                }
            )
        # Mismo cuidado que en los tests de contexto: el AccessError tiene
        # que ser el nuestro, no el de account.move que dispara la
        # valorización de una línea que nace `done`.
        self.assertIn("Intercompany", str(capture.exception))
        self.assertEqual(
            self._quant_qty(move.product_id, move.location_id),
            qty_before,
            "El quant de origen no debe haberse movido",
        )

    def test_line_create_without_picking_id_in_vals_is_also_guarded(self):
        """Critical 2: omitir `picking_id` de los vals no esquiva el guard.

        La línea igual nace `done` (el estado lo hereda del move) y mueve
        los quants, así que el picking se resuelve por `move_id` cuando
        `picking_id` no viene en los vals.
        """
        delivery, _reception = self._create_delivery(qty=10.0)
        move = delivery.move_ids[0]
        with self.assertRaises(AccessError) as capture:
            self.env["stock.move.line"].with_user(self.user_operator).create(
                {
                    "move_id": move.id,
                    "product_id": move.product_id.id,
                    "product_uom_id": move.product_uom.id,
                    "quantity": 3.0,
                    "location_id": move.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                    "company_id": delivery.company_id.id,
                }
            )
        self.assertIn("Intercompany", str(capture.exception))

    def test_line_create_on_plain_picking_is_untouched(self):
        """Critical 2: un picking SIN contraparte no cambia de comportamiento."""
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
        move = (
            self.env["stock.move"]
            .with_user(self.user_operator)
            .create(
                {
                    "name": self.product.name,
                    "product_id": self.product.id,
                    "product_uom_qty": 5.0,
                    "product_uom": self.uom_unit.id,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_id": picking.id,
                }
            )
        )
        line = (
            self.env["stock.move.line"]
            .with_user(self.user_operator)
            .create(
                {
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": self.product.id,
                    "product_uom_id": self.uom_unit.id,
                    "quantity": 2.0,
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                }
            )
        )
        self.assertTrue(line.exists())

    def test_deleting_counterpart_picking_requires_role(self):
        """Important 3: borrar el espejo pendiente desarmaba el guard.

        `user_admin_no_role` es `stock.group_stock_manager` (tiene el ACL
        genérico de borrado) pero NO el rol del módulo: sin este fix
        borraba la recepción espejo `assigned` sin error, y con el espejo
        desaparecía el `counterpart_picking_id` de la entrega -y con él el
        guard-, dejando la entrega VALIDADA editable por cualquiera.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        self.assertEqual(reception.state, "assigned")
        with self.assertRaises(AccessError) as capture:
            reception.with_user(self.user_admin_no_role).unlink()
        self.assertIn("Intercompany", str(capture.exception))
        self.assertTrue(reception.exists())
        self.assertEqual(delivery.counterpart_picking_id, reception)
        move = delivery.move_ids[0]
        with self.assertRaises(AccessError):
            move.with_user(self.user_operator).write({"product_uom_qty": 15.0})
        self.assertEqual(move.product_uom_qty, 10.0)

    def test_deleting_plain_picking_needs_no_role(self):
        """Important 3: un picking sin contraparte se borra como siempre."""
        picking = (
            self.env["stock.picking"]
            .with_user(self.user_admin_no_role)
            .create(
                {
                    "location_id": self.stock_location.id,
                    "location_dest_id": self.custs_location.id,
                    "picking_type_id": self.picking_type_out.id,
                }
            )
        )
        picking.with_user(self.user_admin_no_role).unlink()
        self.assertFalse(picking.exists())

    def test_duplicating_mirror_does_not_copy_links(self):
        """Important 4: los tres campos de vínculo llevan `copy=False`.

        El botón Duplicar estándar sobre el espejo creaba una copia
        apuntando a la MISMA entrega validada, con los moves vinculados:
        dos pickings apuntando a un solo validado, `_get_counterpart_move()`
        (que hace `search(limit=1)`) ambiguo, y una copia en `draft` que es
        una puerta de escritura hacia la entrega de la otra compañía.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        copy = reception.with_user(self.user_manager_both).copy()
        self.assertFalse(copy.counterpart_of_picking_id)
        self.assertFalse(copy.move_ids.filtered("counterpart_of_move_id"))
        self.assertFalse(
            copy.move_line_ids.filtered("counterpart_of_line_id")
        )
        # Duplicar el picking no arrastra las líneas de detalle (core no
        # copia move_line_ids), así que el copy=False de
        # counterpart_of_line_id se verifica duplicando la línea directo:
        # sin esto la aserción de arriba es vacua -verificado revirtiendo
        # ese hunk solo, con el test todavía en verde-.
        line = reception.move_line_ids[0]
        self.assertTrue(line.counterpart_of_line_id)
        self.assertFalse(
            line.with_user(self.user_manager_both).copy().counterpart_of_line_id
        )
        self.assertEqual(
            delivery.counterpart_picking_id,
            reception,
            "La entrega tiene que seguir resolviendo al espejo original",
        )

    def test_demand_sync_notes_posted_on_both_sides(self):
        """Important 5: `product_uom_qty` se propagaba sin dejar nota.

        El §9 del spec exige nota en las dos puntas para todo lo que viaja
        al espejo, y el §7.1 lista `product_uom_qty` entre lo sincronizado:
        un manager bajaba la demanda de la entrega validada y la de la
        recepción de la otra compañía cambiaba sola, sin rastro en ningún
        chatter. Se cuentan las notas NUESTRAS por su marca ("→" con el
        producto), sin depender del idioma de los mensajes de core.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        before_delivery = set(delivery.message_ids.ids)
        before_reception = set(reception.message_ids.ids)
        delivery.move_ids[0].with_user(self.user_manager_both).write(
            {"product_uom_qty": 8.0}
        )
        self.assertEqual(reception.move_ids[0].product_uom_qty, 8.0)
        new_delivery = delivery.message_ids.filtered(
            lambda m: m.id not in before_delivery
        )
        new_reception = reception.message_ids.filtered(
            lambda m: m.id not in before_reception
        )
        own = new_delivery.filtered(
            lambda m: "10.0 → 8.0" in (m.body or "")
        )
        mirrored = new_reception.filtered(
            lambda m: "10.0 → 8.0" in (m.body or "")
        )
        self.assertEqual(
            len(own),
            1,
            f"Falta la nota propia; mensajes: {new_delivery.mapped('body')}",
        )
        self.assertEqual(
            len(mirrored),
            1,
            f"Falta la nota del espejo; mensajes: {new_reception.mapped('body')}",
        )
        self.assertIn(delivery.name, mirrored.body)
        self.assertIn(self.product.display_name, own.body)

    def test_writing_lot_false_on_both_sides_does_not_propagate(self):
        """One-liner 1: `map_lot(recordset vacío)` devuelve un recordset.

        Devolvía `False` crudo, y `False != stock.lot()` da `True`: un
        `write({'lot_id': False})` sobre una línea cuya contraparte tampoco
        tiene lote forzaba un write espurio en la otra compañía, con el
        undo/redo de quants que eso implica sobre una línea `done`.
        """
        delivery, reception = self._create_delivery(qty=10.0)
        line = delivery.move_line_ids[0]
        self.assertFalse(line.lot_id)
        self.assertFalse(reception.move_line_ids[0].lot_id)
        before_reception = len(reception.message_ids)
        model_class = type(self.env["stock.move.line"])
        original_write = model_class.write
        calls = []

        def counting_write(self, vals):
            calls.append(self.ids)
            return original_write(self, vals)

        with patch.object(model_class, "write", counting_write):
            line.with_user(self.user_manager_both).write({"lot_id": False})

        self.assertEqual(
            len(calls),
            1,
            f"No debería propagarse nada al espejo; llamadas: {calls}",
        )
        self.assertEqual(len(reception.message_ids), before_reception)

    def test_priority_false_is_normalized_before_propagating(self):
        """One-liner 2: la normalización `False↔'0'` también al valor.

        Se aplicaba solo a la comparación, así que el `False` crudo viajaba
        igual al espejo y la nota decía "Prioridad: False → …".
        """
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).write({"priority": "1"})
        self.assertEqual(delivery.priority, "1")
        before = set(delivery.message_ids.ids)
        reception.with_user(self.user_manager_both).write({"priority": False})
        self.assertEqual(
            delivery.priority, "0", "Debe llegar la clave normalizada, no False"
        )
        notes = delivery.message_ids.filtered(lambda m: m.id not in before)
        self.assertTrue(notes)
        for body in notes.mapped("body"):
            self.assertNotIn("False", body or "")

    def test_lot_required_message_names_lot_id_only(self):
        """One-liner 3: el mensaje decía "lot_id/lot_name" pero el filtro
        solo mira `lot_id` -y tiene que seguir mirando solo eso: en este
        camino `_action_done()` es un no-op y nadie convierte `lot_name` en
        un `stock.lot` real-."""
        tracked = self.env["product.product"].create(
            {
                "name": "Sync Tracked Msg",
                "type": "consu",
                "is_storable": True,
                "tracking": "lot",
                "categ_id": self.env.ref("product.product_category_all").id,
            }
        )
        tracked.company_id = False
        delivery, reception = self._create_delivery(qty=10.0)
        reception.with_user(self.user_manager_both).button_validate()
        with self.assertRaises(UserError) as capture:
            self.env["stock.move"].with_user(self.user_manager_both).create(
                {
                    "picking_id": delivery.id,
                    "product_id": tracked.id,
                    "product_uom": self.uom_unit.id,
                    "product_uom_qty": 4.0,
                    "location_id": delivery.location_id.id,
                    "location_dest_id": delivery.location_dest_id.id,
                    "name": tracked.name,
                }
            )
        message = str(capture.exception)
        self.assertIn("lot_id", message)
        self.assertNotIn("lot_name", message)
