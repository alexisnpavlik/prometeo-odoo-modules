# -*- coding: utf-8 -*-

from odoo import SUPERUSER_ID, Command, api


def migrate(cr, version):
    """Asigna sucursales a las promociones: las que salen de sus listas (pre-migrate) o,
    si no tenían (bases en 18.0.2.0), su empresa o todas."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    mapping = {}
    cr.execute("SELECT to_regclass('pos_promotion_company_mig')")
    if cr.fetchone()[0]:
        cr.execute("SELECT product_tmpl_id, company_id FROM pos_promotion_company_mig")
        for tmpl_id, company_id in cr.fetchall():
            mapping.setdefault(tmpl_id, []).append(company_id)
        cr.execute("DROP TABLE pos_promotion_company_mig")
    all_companies = env["res.company"].search([])
    templates = env["product.template"].with_context(active_test=False).search([("is_promotion_pack", "=", True)])
    for template in templates:
        company_ids = mapping.get(template.id) or (template.company_id or all_companies).ids
        if template.company_id:
            company_ids = [cid for cid in company_ids if cid == template.company_id.id] or template.company_id.ids
        template.promotion_company_ids = [Command.set(company_ids)]
