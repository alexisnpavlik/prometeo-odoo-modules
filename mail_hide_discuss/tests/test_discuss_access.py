# -*- coding: utf-8 -*-

from odoo.tests import tagged
from odoo.tests.common import HttpCase, JsonRpcException, TransactionCase, new_test_user
from odoo.tools import mute_logger

from ..controllers.discuss_action import is_discuss_action


@tagged("post_install", "-at_install")
class TestDiscussAccess(TransactionCase):
    """Comprueba que Conversaciones quede oculto y bloqueado."""

    def test_discuss_menu_is_inactive(self):
        """El menú raíz de Conversaciones no está disponible."""
        menu = self.env.ref("mail.menu_root_discuss")
        self.assertFalse(menu.active)

    def test_discuss_action_identifiers_are_detected(self):
        """La acción se reconoce por ruta, XML ID e ID numérico."""
        action_id = self.env.ref("mail.action_discuss").id
        self.assertTrue(is_discuss_action("discuss", action_id))
        self.assertTrue(is_discuss_action("mail.action_discuss", action_id))
        self.assertTrue(is_discuss_action(action_id, action_id))
        self.assertTrue(is_discuss_action(str(action_id), action_id))
        self.assertFalse(is_discuss_action("contacts", action_id))


@tagged("post_install", "-at_install")
class TestDiscussHttpAccess(HttpCase):
    """Comprueba el bloqueo mediante el endpoint real de acciones."""

    @classmethod
    def setUpClass(cls):
        """Crea un usuario interno sin privilegios administrativos."""
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            "mail_hide_discuss_user",
            groups="base.group_user",
            password="mail_hide_discuss_user",
        )

    def test_direct_discuss_action_is_denied(self):
        """Una URL directa tampoco puede cargar Conversaciones."""
        self.authenticate(self.user.login, "mail_hide_discuss_user")
        action = self.env.ref("mail.action_discuss")
        for action_id in ("discuss", "mail.action_discuss", action.id):
            with self.assertRaisesRegex(
                JsonRpcException, "odoo.exceptions.AccessError"
            ), mute_logger("odoo.http"):
                self.make_jsonrpc_request(
                    "/web/action/load", {"action_id": action_id}
                )
