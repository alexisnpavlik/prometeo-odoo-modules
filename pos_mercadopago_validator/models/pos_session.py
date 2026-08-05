import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_mercadopago_unmatched(self):
        """Pagos recibidos durante la sesión que quedaron sin imputar.

        El cierre se permite igual: el objetivo es que el faltante se
        descubra en el momento y no una semana después, no bloquear la caja.

        El dominio se arma por método, reusando `_channel_domain()` de cada
        uno, en vez de juntar los `mp_pos_id` de todos los métodos en una
        sola lista `in`: un método mal configurado sin `mp_pos_id` metería un
        `False` en esa lista, y `("mp_pos_id", "in", [..., False])` matchea
        también los pagos por alias (que llegan con `mp_pos_id` vacío),
        mezclando huérfanos de otra caja en este aviso -hallazgo real de la
        Task 9-.
        """
        self.ensure_one()
        methods = self.config_id.payment_method_ids.filtered(
            lambda m: m.use_payment_terminal == "mercadopago_validator"
        )
        if not methods:
            return []
        domain = False
        for method in methods:
            leaf = [("account_id", "=", method.mp_account_id.id)] + method._channel_domain()
            domain = leaf if domain is False else ["|"] + domain + leaf
        payments = self.env["mercadopago.payment"].sudo().search(domain + [
            ("state", "=", "available"),
            ("date_approved", ">=", self.start_at),
        ])
        _logger.info(
            "Sesión %s: %s pago(s) de Mercado Pago sin imputar al momento del cierre",
            self.id, len(payments),
        )
        return [{
            "id": p.id,
            "mp_payment_id": p.mp_payment_id,
            "amount": p.amount,
            "date_approved": p.date_approved.isoformat(),
            "display_payer": p.display_payer or "",
        } for p in payments]
