import re
from pathlib import Path

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAprobacionManual(TransactionCase):
    """Registro auditado de cobros marcados como recibidos sin verificar el pago."""

    def setUp(self):
        """Arma cuenta y método en una compañía activa, explícita.

        En esta base la compañía del superusuario (id 1) está archivada: un
        método de pago creado con ella no es legible por ningún usuario de
        prueba (ver `test_reserva_por_uuid.py`).
        """
        super().setUp()
        self.company = self.env["res.company"].search([], limit=1)
        self.env = self.env(context=dict(self.env.context, allowed_company_ids=self.company.ids))
        self.account = self.env["mercadopago.account"].with_company(self.company).create({
            "name": "Cuenta", "mode": "production", "mp_user_id": "430185252",
            "company_id": self.company.id,
        })
        journal = self.env["account.journal"].search([
            ("type", "=", "bank"), ("company_id", "=", self.company.id),
        ], limit=1)
        self.method = self.env["pos.payment.method"].with_company(self.company).create({
            "name": "MP QR", "journal_id": journal.id,
            "use_payment_terminal": "mercadopago_validator",
            "mp_account_id": self.account.id, "mp_pos_id": "64365871",
            "company_id": self.company.id,
        })

    def test_reason_is_mandatory(self):
        """Sin motivo no hay aprobación manual."""
        with self.assertRaises(UserError):
            self.method.register_manual_approval("uuid-1", "   ")

    def test_uuid_is_validated_like_the_other_rpc_entries(self):
        """I-5: una aprobación con uuid vacío queda inalcanzable para siempre.

        `pos.payment.create()` la busca por uuid: sin uuid válido nunca se
        cierra y el registro queda sin monto, sin venta y sin sesión, es decir
        inservible justo para el control de §9 que lo justifica.
        """
        for bad_uuid in ("", "   ", None, 42, ["uuid-1"]):
            with self.assertRaises(UserError, msg="uuid aceptado: %r" % (bad_uuid,)):
                self.method.register_manual_approval(bad_uuid, "El cliente ya se iba")
        self.assertFalse(self.env["mercadopago.manual.approval"].search([
            ("payment_method_id", "=", self.method.id),
        ]))

    def test_reason_of_a_wrong_type_is_rejected(self):
        """El motivo también llega del navegador: no se asume que sea un string."""
        with self.assertRaises(UserError):
            self.method.register_manual_approval("uuid-1", None)

    def test_approval_records_who_and_when(self):
        """Queda registrado usuario, motivo y momento."""
        self.method.register_manual_approval("uuid-1", "El cliente ya se iba")
        approval = self.env["mercadopago.manual.approval"].search([
            ("pos_payment_uuid", "=", "uuid-1")
        ])
        self.assertEqual(len(approval), 1)
        self.assertEqual(approval.user_id, self.env.user)
        self.assertEqual(approval.reason, "El cliente ya se iba")
        self.assertTrue(approval.create_date)

    def test_creating_the_payment_line_completes_the_approval(self):
        """Al sincronizarse la orden, la aprobación queda con monto, venta y sesión.

        `register_manual_approval()` sólo conoce el uuid del navegador; recién
        cuando `pos.payment.create()` corre existe un `pos.payment` real. Sin
        este cierre el reporte de aprobaciones manuales -el control que
        justifica la existencia del modelo- saldría sin plata ni venta.
        """
        self.method.register_manual_approval("uuid-1", "El cliente ya se iba")

        config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja test aprobación manual", "company_id": self.company.id,
        })
        config.write({"payment_method_ids": [(4, self.method.id)]})
        config.open_ui()
        order = self.env["pos.order"].create({
            "session_id": config.current_session_id.id, "amount_total": 1500.0,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        line = self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id,
            "amount": 1500.0, "mercadopago_uuid": "uuid-1",
        })

        approval = self.env["mercadopago.manual.approval"].search([
            ("pos_payment_uuid", "=", "uuid-1")
        ])
        self.assertEqual(approval.pos_payment_id, line)
        self.assertEqual(approval.pos_order_id, order)
        self.assertEqual(approval.pos_session_id, order.session_id)
        self.assertEqual(approval.amount, 1500.0)

        self.assertTrue(line.is_manual_approval)
        self.assertEqual(line.manual_reason, "El cliente ya se iba")
        self.assertEqual(line.manual_approved_by_user_id, self.env.user)
        self.assertTrue(line.manual_approved_at)

    def test_the_whole_chain_from_what_the_frontend_actually_sends(self):
        """B-1: el encadenamiento completo, con el uuid puesto como lo hace la interfaz.

        El test de arriba escribía `mercadopago_uuid` a mano, cosa que el
        frontend **no hacía**: `onManualApproval` llamaba a
        `register_manual_approval` y nunca seteaba el campo en la línea. Como
        `pos.payment.create()` arranca con `if not line.mercadopago_uuid:
        continue`, todo `_close_manual_approval()` era código muerto desde la
        interfaz y el reporte de aprobaciones manuales salía sin monto y sin
        venta -justo el cruce contra los huérfanos que el spec §9 declara
        obligatorio-.

        Acá se reproduce la secuencia de la interfaz de punta a punta: el mismo
        uuid de la línea del navegador va al registro de la aprobación y al
        campo que viaja al servidor, y se verifica todo lo que tiene que quedar
        atado a los dos lados.
        """
        browser_uuid = "0198f4c1-3c2a-7d11-9f0e-manual"

        # 1. Lo que hace onManualApproval: registrar la aprobación con el uuid
        #    de la línea del navegador...
        self.method.register_manual_approval(browser_uuid, "No llegó el pago y el cliente se iba")

        approval = self.env["mercadopago.manual.approval"].search([
            ("pos_payment_uuid", "=", browser_uuid),
        ])
        self.assertEqual(len(approval), 1)
        self.assertFalse(approval.pos_payment_id, "Todavía no hay línea en el servidor")
        self.assertEqual(approval.amount, 0.0)

        # 2. ...y marcar la línea con ese mismo uuid, que es lo que faltaba.
        config = self.env["pos.config"].with_company(self.company).create({
            "name": "Caja test cadena manual", "company_id": self.company.id,
        })
        config.write({"payment_method_ids": [(4, self.method.id)]})
        config.open_ui()
        order = self.env["pos.order"].create({
            "session_id": config.current_session_id.id, "amount_total": 2300.0,
            "amount_tax": 0, "amount_paid": 0, "amount_return": 0,
        })
        line = self.env["pos.payment"].create({
            "pos_order_id": order.id, "payment_method_id": self.method.id,
            "amount": 2300.0, "mercadopago_uuid": browser_uuid,
        })

        # 3. La aprobación queda utilizable para el control de §9.
        approval.invalidate_recordset()
        self.assertEqual(approval.pos_payment_id, line)
        self.assertEqual(approval.pos_order_id, order)
        self.assertEqual(approval.pos_session_id, order.session_id)
        self.assertEqual(approval.amount, 2300.0)
        self.assertEqual(approval.user_id, self.env.user)

        # 4. Y la línea queda marcada como cobro sin verificar.
        self.assertTrue(line.is_manual_approval)
        self.assertEqual(line.manual_reason, "No llegó el pago y el cliente se iba")
        self.assertEqual(line.manual_approved_by_user_id, self.env.user)

    def test_the_frontend_sets_the_uuid_on_manual_approval(self):
        """El eslabón que faltaba vive en el JS: se verifica sobre el fuente.

        No hay navegador en este entorno y el bug era exactamente una línea
        ausente en `onManualApproval`. El test de arriba prueba la cadena del
        lado del servidor asumiendo que el uuid llega; éste prueba que el
        frontend lo manda, que es lo que estaba roto.
        """
        source = Path(__file__).resolve().parents[1].joinpath(
            "static", "src", "app", "payment_mercadopago_validator.js"
        ).read_text(encoding="utf-8")

        # Se delimita entre handlers y no por llaves: contar llaves sobre JS a
        # mano es más frágil que apoyarse en el handler siguiente.
        block = re.search(r"onManualApproval:(.*?)onCancel:", source, re.S)
        self.assertTrue(block, "No se encontró el handler onManualApproval en el fuente")
        self.assertIn(
            "line.mercadopago_uuid = line.uuid", block.group(1),
            "onManualApproval no marca la línea con su uuid: pos_payment.create() "
            "la saltea y la aprobación manual queda sin monto ni venta.",
        )
