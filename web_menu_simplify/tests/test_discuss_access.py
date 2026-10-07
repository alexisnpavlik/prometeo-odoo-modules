# -*- coding: utf-8 -*-

from odoo.tests import tagged
from odoo.tests.common import HttpCase, JsonRpcException, new_test_user
from odoo.tools import mute_logger

from ..controllers.discuss_action import is_discuss_action


@tagged("post_install", "-at_install")
class TestDiscussAccess(HttpCase):
    """Comprueba que Conversaciones se oculte y bloquee según la opción de Ajustes."""

    @classmethod
    def setUpClass(cls):
        """Crea un usuario interno sin privilegios administrativos."""
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            "web_menu_simplify_user",
            groups="base.group_user",
            password="web_menu_simplify_user",
        )
        cls.discuss_action = cls.env.ref("mail.action_discuss")
        cls.discuss_menu = cls.env.ref("mail.menu_root_discuss")

    def _load_discuss(self):
        """Pide la acción Conversaciones por cada forma de identificarla."""
        for action_id in ("discuss", "mail.action_discuss", self.discuss_action.id):
            self.make_jsonrpc_request("/web/action/load", {"action_id": action_id})

    def test_action_identifiers_are_detected(self):
        """La acción se reconoce por ruta, XML ID e ID numérico."""
        action_id = self.discuss_action.id
        self.assertTrue(is_discuss_action("discuss", action_id))
        self.assertTrue(is_discuss_action("mail.action_discuss", action_id))
        self.assertTrue(is_discuss_action(str(action_id), action_id))
        self.assertFalse(is_discuss_action("contacts", action_id))

    def test_option_on_hides_and_blocks(self):
        """Con la opción activada (por defecto) el menú no se ve y la URL falla."""
        self.env["ir.config_parameter"].set_param("web_menu_simplify.hide_discuss", "1")
        visible = self.env["ir.ui.menu"].with_user(self.user)._visible_menu_ids(False)
        self.assertNotIn(self.discuss_menu.id, visible)
        self.authenticate(self.user.login, "web_menu_simplify_user")
        with self.assertRaisesRegex(JsonRpcException, "odoo.exceptions.AccessError"), mute_logger("odoo.http"):
            self._load_discuss()

    def test_option_off_shows_and_allows(self):
        """Con la opción apagada el menú vuelve y la acción carga."""
        self.env["ir.config_parameter"].set_param("web_menu_simplify.hide_discuss", "0")
        visible = self.env["ir.ui.menu"].with_user(self.user)._visible_menu_ids(False)
        self.assertIn(self.discuss_menu.id, visible)
        self.authenticate(self.user.login, "web_menu_simplify_user")
        self._load_discuss()
