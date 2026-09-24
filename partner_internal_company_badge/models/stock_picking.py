from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    partner_is_internal_company = fields.Boolean(related="partner_id.is_internal_company")
    partner_internal_company_name = fields.Char(related="partner_id.internal_company_name")
