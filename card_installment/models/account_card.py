##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import api, fields, models


class AccountCard(models.Model):
    _name = "account.card"
    _description = "Credit Card"
    _inherit = ["pos.load.mixin"]
    _check_company_auto = True

    @api.model
    def _load_pos_data_fields(self, config_id):
        return ["id", "name", "company_id", "active"]

    @api.model
    def _get_pos_load_domain(self, config_id):
        return [("company_id", "=", config_id.company_id.id)]

    name = fields.Char(
        "name",
        required=True,
    )
    installment_ids = fields.One2many(
        "account.card.installment",
        "card_id",
        string="Installments",
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company.id)
    active = fields.Boolean(default=True)

    def map_card_values(self):
        self.ensure_one()
        return {
            "name": self.name,
            "id": self.id,
            "installments": [],
        }
