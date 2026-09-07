import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Da la pestaña Punto de venta a los usuarios internos al subir a 1.1.0.

    El data file con noupdate solo corre en instalaciones nuevas: en las bases
    donde el módulo ya estaba instalado el default hay que aplicarlo acá.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    group_user = env.ref("base.group_user", raise_if_not_found=False)
    group_pos = env.ref(
        "product_default_settings.group_show_page_pos", raise_if_not_found=False
    )
    if not group_user or not group_pos:
        _logger.warning("No se encontraron los grupos para aplicar el default de POS")
        return
    if group_pos in group_user.implied_ids:
        return
    group_user.write({"implied_ids": [(4, group_pos.id)]})
    _logger.info("Pestaña Punto de venta habilitada para los usuarios internos")
