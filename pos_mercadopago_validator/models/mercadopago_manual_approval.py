from odoo import fields, models


class MercadoPagoManualApproval(models.Model):
    """Registro auditado de un cobro marcado como recibido sin verificar el pago.

    Lo crea `pos.payment.method.register_manual_approval()` en el momento del
    cobro, cuando la línea todavía vive sólo en el navegador y sólo se conoce
    el `pos_payment_uuid`. `pos.payment.create()` completa el resto -monto,
    venta y sesión- cuando la orden se sincroniza (ver Task 12).
    """

    _name = "mercadopago.manual.approval"
    _description = "Cobro aprobado sin verificación de pago"
    _order = "create_date desc"

    payment_method_id = fields.Many2one("pos.payment.method", required=True, readonly=True)
    pos_payment_uuid = fields.Char(required=True, readonly=True, index=True)
    pos_payment_id = fields.Many2one("pos.payment", readonly=True)
    pos_order_id = fields.Many2one("pos.order", readonly=True)
    pos_session_id = fields.Many2one("pos.session", readonly=True)
    amount = fields.Monetary(readonly=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, readonly=True
    )
    reason = fields.Char(required=True, readonly=True)
    user_id = fields.Many2one("res.users", required=True, readonly=True)
