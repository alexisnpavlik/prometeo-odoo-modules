import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Grupo viejo (por usuario) -> ajuste global nuevo.
GROUP_TO_SETTING = {
    "group_edit_product_defaults": "edit_defaults",
    "group_show_page_variants": "show_page_variants",
    "group_show_page_sales": "show_page_sales",
    "group_show_page_purchase": "show_page_purchase",
    "group_show_page_inventory": "show_page_inventory",
    "group_show_page_pos": "show_page_pos",
}


def migrate(cr, version):
    """Pasa los grupos por usuario a ajustes globales (ir.config_parameter).

    Un ajuste queda prendido si el grupo estaba dado a todos los usuarios
    internos (lo que hacía la casilla vieja de Ajustes). Los grupos se borran
    solos al terminar el update, porque ya no están en los datos del módulo.
    Corre en post porque en ese momento los grupos todavía existen.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    icp = env["ir.config_parameter"]
    group_user = env.ref("base.group_user")
    for group_xmlid, key in GROUP_TO_SETTING.items():
        param = "product_default_settings." + key
        if icp.get_param(param):
            continue
        group = env.ref("product_default_settings." + group_xmlid, raise_if_not_found=False)
        enabled = bool(group) and group in group_user.implied_ids
        icp.set_param(param, str(enabled))
        _logger.info(
            "product_default_settings: %s=%s (%s usuarios tenían el grupo)",
            key, enabled, len(group.users) if group else 0,
        )
