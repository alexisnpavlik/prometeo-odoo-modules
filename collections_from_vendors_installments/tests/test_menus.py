# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviMenus(CviCommon):
    """Qué pantalla abre el módulo al entrar, según el perfil."""

    def _user(self, login, groups):
        return self.env["res.users"].create({
            "name": login,
            "login": login,
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref(
                    "collections_from_vendors_installments.%s" % group
                ).id for group in groups
            ] + [self.env.ref("base.group_user").id])],
        })

    def _entry_action(self, user):
        """Acción que Odoo abre al hacer clic en la aplicación, para este usuario.

        Reproduce lo que hace el cliente web: recorre el árbol de menús en orden y se
        queda con la primera opción con acción que el usuario tenga permitida.
        """
        menus = self.env["ir.ui.menu"].with_user(user).load_menus(False)
        root_id = self.env.ref(
            "collections_from_vendors_installments.menu_cvi_root"
        ).id

        def walk(menu_id):
            menu = menus[menu_id]
            if menu["action"]:
                return menu["action"]
            for child_id in menu["children"]:
                found = walk(child_id)
                if found:
                    return found
            return None

        action_ref = walk(root_id)
        self.assertTrue(action_ref, "El módulo no abre ninguna acción para %s" % user.name)
        model, action_id = action_ref.split(",")
        return self.env[model].browse(int(action_id))

    def test_entering_the_module_never_opens_a_dialog(self):
        """Entrar al módulo no puede disparar un asistente.

        Con "Nueva venta" primera en el menú, abrir la aplicación lanzaba el diálogo del
        DNI sin que nadie lo pidiera: cargar una venta es una decisión, no la pantalla de
        bienvenida.
        """
        for groups in (
            ["group_cvi_vendor"],
            ["group_cvi_collector"],
            ["group_cvi_vendor", "group_cvi_collector"],
            ["group_cvi_manager"],
        ):
            user = self._user("cvi_menu_%s" % "_".join(groups), groups)
            action = self._entry_action(user)
            self.assertNotEqual(
                action.target, "new",
                "El perfil %s entra al módulo con un diálogo: %s" % (groups, action.name),
            )

    def test_a_vendor_lands_on_his_sales(self):
        action = self._entry_action(self._user("cvi_menu_landing_vendor", ["group_cvi_vendor"]))
        self.assertEqual(
            action,
            self.env.ref("collections_from_vendors_installments.action_cvi_card_my_sales"),
        )

    def test_a_collector_lands_on_the_agenda(self):
        action = self._entry_action(
            self._user("cvi_menu_landing_collector", ["group_cvi_collector"])
        )
        self.assertEqual(
            action,
            self.env.ref("collections_from_vendors_installments.action_cvi_agenda"),
        )

    def test_a_manager_lands_on_the_dashboard(self):
        action = self._entry_action(self._user("cvi_menu_landing_manager", ["group_cvi_manager"]))
        self.assertEqual(
            action,
            self.env.ref("collections_from_vendors_installments.action_cvi_dashboard"),
        )
