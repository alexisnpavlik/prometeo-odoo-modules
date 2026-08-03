import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosPayment(models.Model):
    _inherit = "pos.payment"

    mercadopago_payment_id = fields.Many2one(
        "mercadopago.payment", string="Pago de Mercado Pago", readonly=True,
    )
    mercadopago_reference = fields.Char(
        related="mercadopago_payment_id.mp_payment_id", string="Referencia MP", store=True,
    )
    mercadopago_uuid = fields.Char(
        help="uuid de la línea en el navegador. Vincula la reserva hecha durante el cobro (Task 11).",
    )
    is_manual_approval = fields.Boolean(readonly=True)
    manual_reason = fields.Char(readonly=True)
    manual_approved_by_user_id = fields.Many2one("res.users", readonly=True)
    manual_approved_at = fields.Datetime(readonly=True)

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Incluye el uuid de vínculo en los campos que sincroniza el POS.

        Sin esto la línea de pago que arma el navegador nunca lleva el uuid al
        servidor, y `create()` no tiene con qué cerrar la reserva.
        """
        return super()._load_pos_data_fields(config_id) + ["mercadopago_uuid"]

    @api.model_create_multi
    def create(self, vals_list):
        """Convierte la reserva por uuid (Task 11) en la imputación definitiva.

        Durante el cobro la línea de pago vive sólo en el navegador, así que el
        pago se reservó contra su uuid con `reserve_for_uuid()`. Recién acá,
        cuando la orden se sincroniza y existe un `pos.payment` real con id, se
        puede completar `pos_payment_id` y dejar que actúe el índice único
        parcial de `mercadopago.payment`.

        Una línea con un uuid sin reserva asociada se loguea y no rompe la
        creación: frenar la venta acá dejaría la sesión del POS sin poder
        sincronizar y al cajero sin poder cerrar caja, que es peor que un pago
        de Mercado Pago sin vincular. La anomalía queda visible igual: el
        registro de `mercadopago.payment`, si existe, sigue en estado
        `matched` sin `pos_payment_id`, buscable desde el backoffice.
        """
        lines = super().create(vals_list)
        Inbox = self.env["mercadopago.payment"].sudo()
        for line in lines:
            if not line.mercadopago_uuid:
                continue
            # Orden determinístico: si por algún camino hubiera más de una
            # reserva viva con el mismo uuid -no debería, reserve_for_uuid()
            # ya las rechaza- no se elige a ciegas entre ellas.
            reserved = Inbox.search([
                ("pos_payment_uuid", "=", line.mercadopago_uuid),
                ("state", "=", "matched"),
                ("pos_payment_id", "=", False),
            ], order="id asc")
            if not reserved:
                _logger.warning(
                    "La línea de pago %s declara el uuid %s pero no hay ninguna "
                    "reserva de Mercado Pago asociada",
                    line.id, line.mercadopago_uuid,
                )
                continue
            if len(reserved) > 1:
                _logger.error(
                    "Hay %s reservas vivas de Mercado Pago para el uuid %s; se "
                    "cierra la más antigua (%s) y las demás quedan huérfanas",
                    len(reserved), line.mercadopago_uuid, reserved.mapped("mp_payment_id"),
                )
            reserved = reserved[0]
            order = line.pos_order_id
            reserved.write({
                "pos_payment_id": line.id,
                "pos_order_id": order.id,
                "pos_session_id": order.session_id.id,
                "amount_difference": line.amount - reserved.amount,
            })
            line.mercadopago_payment_id = reserved.id
            _logger.info(
                "Reserva de Mercado Pago %s cerrada sobre la línea de pago %s",
                reserved.mp_payment_id, line.id,
            )
        return lines
