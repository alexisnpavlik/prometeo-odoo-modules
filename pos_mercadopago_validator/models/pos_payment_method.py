import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    mp_account_id = fields.Many2one(
        "mercadopago.account", string="Cuenta de Mercado Pago",
        help="Varias cajas pueden apuntar a la misma cuenta con QR distintos.",
    )
    mp_pos_id = fields.Char(
        string="ID del QR (caja)",
        help="pos_id del QR de esta caja. Separa la bandeja de las demás cajas.",
    )
    accept_alias_payments = fields.Boolean(
        string="Aceptar cobros por alias",
        help="Los cobros por alias no traen caja ni pagador identificable.",
    )
    auto_impute_single_match = fields.Boolean(
        string="Imputar solo cuando hay un único candidato",
        help="Desactivado, el cajero confirma siempre.",
    )
    search_window_minutes = fields.Integer(default=5, required=True)
    poll_interval_seconds = fields.Integer(default=10, required=True)
    amount_tolerance = fields.Float(
        default=0.0,
        help="0 significa sólo coincidencia exacta de monto.",
    )
    require_manager_for_manual = fields.Boolean(
        string="Exigir encargado para aprobación manual",
    )

    def _get_payment_terminal_selection(self):
        """Agrega el validador de Mercado Pago al selector de terminal."""
        return super()._get_payment_terminal_selection() + [
            ("mercadopago_validator", "Mercado Pago - Validador de QR")
        ]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos que el POS sincroniza al navegador.

        Whitelist explícita: ninguna credencial entra acá. Ver RNF-002.
        """
        return super()._load_pos_data_fields(config_id) + [
            "mp_pos_id", "accept_alias_payments", "auto_impute_single_match",
            "search_window_minutes", "poll_interval_seconds", "amount_tolerance",
            "require_manager_for_manual",
        ]

    def _check_pos_access(self):
        """Verifica que quien llama por RPC sea un usuario del POS."""
        if not self.env.user.has_group("point_of_sale.group_pos_user"):
            raise AccessError(_("No tenés acceso a la bandeja de Mercado Pago."))

    STALE_AFTER_SECONDS = 60

    def _inbox_domain(self):
        """Filtro de presentación: la bandeja de esta caja (§6.2 del spec)."""
        self.ensure_one()
        window_start = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=self.search_window_minutes
        )
        domain = [
            ("account_id", "=", self.mp_account_id.id),
            ("state", "=", "available"),
            ("date_approved", ">=", window_start),
        ]
        channel = ["|", ("mp_pos_id", "=", self.mp_pos_id), ("source", "=", "alias")] \
            if self.accept_alias_payments else [("mp_pos_id", "=", self.mp_pos_id)]
        return domain + channel

    def get_mp_inbox(self, amount):
        """Devuelve la bandeja de esta caja para el monto pedido.

        Nunca consulta a Mercado Pago: lee de la base de Odoo. El ingestor
        server-side es el único que habla con la API.
        """
        self.ensure_one()
        self._check_pos_access()
        Inbox = self.env["mercadopago.payment"].sudo()
        available = Inbox.search(self._inbox_domain())

        tolerance = self.amount_tolerance or 0.0
        matching = available.filtered(lambda p: abs(p.amount - amount) <= tolerance)
        account = self.mp_account_id.sudo()
        last_sync = account.last_sync_at
        stale = not last_sync or (
            fields.Datetime.now() - last_sync
        ).total_seconds() > self.STALE_AFTER_SECONDS

        return {
            "matching": [self._serialize_inbox_line(p, amount) for p in matching],
            "others": [self._serialize_inbox_line(p, amount) for p in (available - matching)],
            "others_count": len(available - matching),
            "last_sync_at": last_sync and last_sync.isoformat() or False,
            "stale": stale,
        }

    def _serialize_inbox_line(self, payment, requested_amount):
        """Arma la fila que ve el cajero. Sin datos que no correspondan."""
        return {
            "id": payment.id,
            "mp_payment_id": payment.mp_payment_id,
            "amount": payment.amount,
            "date_approved": payment.date_approved.isoformat(),
            "display_payer": payment.display_payer or "",
            "source": payment.source,
            "difference": round(requested_amount - payment.amount, 2),
        }

    def impute_mp_payment(self, mp_payment_id, pos_payment_id, ambiguous=False):
        """Imputa un pago a una línea. Devuelve el error de carrera si lo hay."""
        self.ensure_one()
        self._check_pos_access()
        payment = self.env["mercadopago.payment"].sudo().browse(mp_payment_id)
        pos_payment = self.env["pos.payment"].browse(pos_payment_id)
        try:
            payment.impute(pos_payment, ambiguous=ambiguous)
        except UserError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "mp_payment_id": payment.mp_payment_id}
