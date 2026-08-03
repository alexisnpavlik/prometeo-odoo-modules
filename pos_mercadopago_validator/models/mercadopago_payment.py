import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MercadoPagoPayment(models.Model):
    _name = "mercadopago.payment"
    _description = "Pago recibido en Mercado Pago"
    _order = "date_approved desc"

    mp_payment_id = fields.Char(required=True, index=True, readonly=True)
    account_id = fields.Many2one("mercadopago.account", required=True, readonly=True, ondelete="restrict")

    amount = fields.Monetary(
        required=True, readonly=True,
        help="transaction_amount de Mercado Pago: lo que pagó el cliente, antes de retenciones.",
    )
    currency_id = fields.Many2one("res.currency", readonly=True)
    date_approved = fields.Datetime(required=True, readonly=True, index=True)

    source = fields.Selection(
        [("qr", "QR"), ("alias", "Alias / CVU")],
        required=True, readonly=True,
    )
    mp_pos_id = fields.Char(string="QR / Caja", readonly=True, index=True)
    payer_bank_name = fields.Char(string="Banco de origen", readonly=True)
    payer_vat = fields.Char(string="CUIT del pagador", readonly=True)
    payer_email = fields.Char(readonly=True)
    mp_payer_id = fields.Char(string="ID de pagador", readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", string="Cliente", readonly=True)
    payment_method_detail = fields.Char(readonly=True)
    raw_status = fields.Char(readonly=True)

    state = fields.Selection(
        [("available", "Disponible"), ("matched", "Imputado"), ("discarded", "Descartado")],
        default="available", required=True, index=True,
    )
    pos_payment_id = fields.Many2one("pos.payment", readonly=True, ondelete="set null")
    pos_order_id = fields.Many2one("pos.order", readonly=True)
    pos_session_id = fields.Many2one("pos.session", readonly=True)
    matched_by_user_id = fields.Many2one("res.users", readonly=True)
    matched_at = fields.Datetime(readonly=True)
    amount_difference = fields.Monetary(readonly=True)
    ambiguous_pick = fields.Boolean(
        readonly=True,
        help="Se eligió entre candidatos que no podían distinguirse entre sí.",
    )

    display_payer = fields.Char(compute="_compute_display_payer", string="Pagador")

    _sql_constraints = [
        ("mp_payment_id_uniq", "unique(mp_payment_id)",
         "Ese pago de Mercado Pago ya está en la bandeja."),
    ]

    def init(self):
        """Crea el índice único parcial que garantiza una imputación por línea."""
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mercadopago_payment_pos_payment_uniq
            ON mercadopago_payment (pos_payment_id)
            WHERE pos_payment_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS mercadopago_payment_window_idx
            ON mercadopago_payment (account_id, state, date_approved)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS mercadopago_payment_amount_idx
            ON mercadopago_payment (state, amount)
        """)

    @api.depends("partner_id", "payer_bank_name", "payer_vat", "source")
    def _compute_display_payer(self):
        """Elige el mejor identificador disponible según el canal del pago."""
        for payment in self:
            if payment.partner_id:
                payment.display_payer = payment.partner_id.name
            elif payment.payer_vat:
                payment.display_payer = payment.payer_vat
            elif payment.payer_bank_name:
                payment.display_payer = payment.payer_bank_name
            else:
                payment.display_payer = False
