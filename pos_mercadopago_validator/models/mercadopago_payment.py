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

    @api.model
    def ingest_raw(self, account, raw_payments):
        """Upsert idempotente de pagos crudos. Único camino de escritura.

        Tanto el webhook como el cron entran por acá: dos caminos distintos para
        el mismo dato es como aparecen las inconsistencias irreproducibles.
        """
        from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider

        provider = MercadoPagoInboxProvider(client=None, mp_user_id=account.mp_user_id)
        currency = account.company_id.currency_id
        created = self.browse()

        for raw in raw_payments:
            if not provider.is_ingestable(raw):
                continue
            values = provider.normalize(raw)
            existing = self.search([("mp_payment_id", "=", values["mp_payment_id"])], limit=1)
            if existing:
                # Nunca se reabre un pago ya imputado ni se pisa su vínculo.
                if existing.state == "available":
                    existing.write(self._values_without_state(values))
                continue
            values.update({
                "account_id": account.id,
                "currency_id": currency.id,
                "state": "available",
                "partner_id": self._resolve_partner(values).id,
            })
            created |= self.create(values)

        _logger.info(
            "Ingesta Mercado Pago cuenta %s: %s pagos nuevos de %s recibidos",
            account.name, len(created), len(raw_payments),
        )
        return created

    @api.model
    def _values_without_state(self, values):
        """Quita del dict las claves que no deben pisarse en una reingesta."""
        return {k: v for k, v in values.items() if k not in ("state", "mp_payment_id")}

    @api.model
    def _resolve_partner(self, values):
        """Busca el cliente por CUIT y, si no, por mapeo previo del payer id."""
        Partner = self.env["res.partner"]
        if values.get("payer_vat"):
            partner = Partner.search([("vat", "=", values["payer_vat"])], limit=1)
            if partner:
                return partner
        if values.get("mp_payer_id"):
            mapped = self.search([
                ("mp_payer_id", "=", values["mp_payer_id"]),
                ("partner_id", "!=", False),
            ], limit=1)
            if mapped:
                return mapped.partner_id
        return Partner.browse()

    def _notify_open_sessions(self):
        """Avisa por bus a las cajas con sesión abierta. Se completa en Task 10."""
        return True
