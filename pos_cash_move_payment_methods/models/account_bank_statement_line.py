from odoo import fields, models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    # Campo propio y no pos_session_id: el core suma pos_session_id como efectivo en el arqueo.
    pos_move_session_id = fields.Many2one(
        "pos.session", string="Sesión POS (ingreso/retiro)", index="btree_not_null", readonly=True
    )
    pos_move_payment_method_id = fields.Many2one(
        "pos.payment.method", string="Método de pago POS", readonly=True
    )
