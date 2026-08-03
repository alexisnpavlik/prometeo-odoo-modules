from odoo import fields, models


class PosPayment(models.Model):
    _inherit = "pos.payment"

    mercadopago_payment_id = fields.Many2one(
        "mercadopago.payment", string="Pago de Mercado Pago", readonly=True,
    )
    mercadopago_reference = fields.Char(
        related="mercadopago_payment_id.mp_payment_id", string="Referencia MP", store=True,
    )
    is_manual_approval = fields.Boolean(readonly=True)
    manual_reason = fields.Char(readonly=True)
    manual_approved_by_user_id = fields.Many2one("res.users", readonly=True)
    manual_approved_at = fields.Datetime(readonly=True)
