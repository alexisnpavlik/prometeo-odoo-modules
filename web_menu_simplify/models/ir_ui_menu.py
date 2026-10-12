# -*- coding: utf-8 -*-

from odoo import api, models

from .simplify_options import APP_START_OPTIONS, MENU_OPTIONS, is_option_active

# Apps que van primero en el menú, en este orden; la primera es la que se abre
# al iniciar sesión.
FIRST_MENU_XMLIDS = ("point_of_sale.menu_point_root",)

# Menús visibles solo para el administrador (base.group_system). No es
# configurable: apagarlo dejaría a cualquiera entrar a estos mismos ajustes.
ADMIN_ONLY_MENU_XMLIDS = (
    "base.menu_administration",
    "base.menu_management",
)


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _menu_ids_from_xmlids(self, xmlids):
        """Devuelve los ids de los menús existentes y de todos sus submenús."""
        root_ids = [
            menu_id
            for menu_id in (
                self.env["ir.model.data"]._xmlid_to_res_id(xmlid, raise_if_not_found=False)
                for xmlid in xmlids
            )
            if menu_id
        ]
        if not root_ids:
            return set()
        menus = self.with_context({"ir.ui.menu.full_list": True}).sudo().search(
            [("id", "child_of", root_ids)]
        )
        return set(menus.ids)

    @api.model
    def _visible_menu_ids(self, debug=False):
        """Resta los menús de las opciones activadas; el admin en modo debug ve todo."""
        visible = super()._visible_menu_ids(debug=debug)
        is_admin = self.env.user.has_group("base.group_system")
        if is_admin and debug:
            return visible
        hidden_xmlids = [
            xmlid
            for key, xmlids in MENU_OPTIONS.items()
            if is_option_active(self.env, key)
            for xmlid in xmlids
        ]
        if not is_admin:
            hidden_xmlids += ADMIN_ONLY_MENU_XMLIDS
        return visible - self._menu_ids_from_xmlids(hidden_xmlids)

    @api.model
    def load_menus(self, debug):
        """Pone primero las apps de FIRST_MENU_XMLIDS (el webclient abre la primera) y aplica las acciones de inicio."""
        menus = super().load_menus(debug)
        root = menus["root"]
        first_ids = [
            self.env["ir.model.data"]._xmlid_to_res_id(xmlid, raise_if_not_found=False)
            for xmlid in FIRST_MENU_XMLIDS
        ]
        first_ids = [menu_id for menu_id in first_ids if menu_id in root["children"]]
        others = [menu_id for menu_id in root["children"] if menu_id not in first_ids]
        # Copia: el resultado de super() puede venir de la caché.
        menus = dict(menus, root=dict(root, children=first_ids + others))
        return self._apply_app_start_actions(menus)

    def _apply_app_start_actions(self, menus):
        """Hace que las apps de las opciones activadas abran en la acción configurada."""
        model_data = self.env["ir.model.data"]
        for key, apps in APP_START_OPTIONS.items():
            if not is_option_active(self.env, key):
                continue
            for app_xmlid, action_xmlid in apps.items():
                app_id = model_data._xmlid_to_res_id(app_xmlid, raise_if_not_found=False)
                action = self.env.ref(action_xmlid, raise_if_not_found=False)
                if app_id in menus and action:
                    menus[app_id] = dict(menus[app_id], action="%s,%s" % (action._name, action.id))
        return menus
