# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, Command, api


def migrate(cr, version):
    """Las promociones que ya existían siguen aplicándose en todas las listas de su empresa."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = env["product.template"].with_context(active_test=False).search([("is_promotion_pack", "=", True)])
    for template in templates.filtered(lambda t: not t.promotion_pricelist_ids):
        domain = [("company_id", "in", [False, template.company_id.id])] if template.company_id else []
        template.promotion_pricelist_ids = [Command.set(env["product.pricelist"].search(domain).ids)]
