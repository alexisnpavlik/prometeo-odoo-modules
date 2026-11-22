# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Quita el grupo de exportación que Ajustes daba por defecto.

    Saca la implicación desde base.group_system y el grupo a los
    administradores que lo recibieron por esa vía. Los usuarios que no
    son administradores conservan el grupo si se lo asignaron a mano.
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    export_group = env.ref('product_stock_export_restrict.group_product_stock_export', raise_if_not_found=False)
    system_group = env.ref('base.group_system')
    if not export_group:
        return
    system_group.write({'implied_ids': [(3, export_group.id)]})
    admins = system_group.with_context(active_test=False).users.filtered(lambda u: export_group in u.groups_id)
    admins.write({'groups_id': [(3, export_group.id)]})
    print(f"product_stock_export_restrict: grupo quitado a {len(admins)} administradores")
