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

        Una línea con un uuid sin reserva asociada puede corresponder a una
        aprobación manual (Task 12, sin pago verificado): se intenta cerrar esa
        en su lugar antes de darla por huérfana. Si tampoco hay aprobación, se
        loguea y no rompe la creación: frenar la venta acá dejaría la sesión
        del POS sin poder sincronizar y al cajero sin poder cerrar caja, que es
        peor que un pago de Mercado Pago sin vincular. La anomalía queda
        visible igual: el registro de `mercadopago.payment`, si existe, sigue
        en estado `matched` sin `pos_payment_id`, buscable desde el backoffice.

        `mercadopago_uuid` lo pone el navegador, así que la búsqueda no puede
        confiar en el uuid solo: se acota por cuenta y canal (QR/alias) del
        `payment_method_id` de la línea, con `_channel_domain()` -el mismo
        criterio de pertenencia que usa `reserve_for_uuid()` vía
        `_find_inbox_line()` y que usa `revert_mp_reservation_by_uuid()` vía
        `account_id`-. Sin este filtro, una línea de otra caja o de otra
        cuenta que declarara el uuid de una reserva viva ajena se la
        quedaría, y acá no hay vuelta atrás: es la operación que deja el pago
        imputado a una venta.
        """
        lines = super().create(vals_list)
        Inbox = self.env["mercadopago.payment"].sudo()
        Approval = self.env["mercadopago.manual.approval"].sudo()
        for line in lines:
            if not line.mercadopago_uuid:
                continue
            method = line.payment_method_id
            # Orden determinístico: si por algún camino hubiera más de una
            # reserva viva con el mismo uuid -no debería, reserve_for_uuid()
            # ya las rechaza- no se elige a ciegas entre ellas.
            reserved = Inbox.search([
                ("pos_payment_uuid", "=", line.mercadopago_uuid),
                ("state", "=", "matched"),
                ("pos_payment_id", "=", False),
                ("account_id", "=", method.mp_account_id.id),
            ] + method._channel_domain(), order="id asc")
            if not reserved:
                line._close_manual_approval(Approval)
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

    def _close_manual_approval(self, Approval):
        """Completa la aprobación manual pendiente de esta línea, si hay una.

        `register_manual_approval()` (Task 11) sólo conoce el uuid del
        navegador al momento del cobro: la aprobación queda creada sin monto,
        sin venta y sin sesión. Recién acá, con la línea real sincronizada, se
        puede completar -si no, el reporte de aprobaciones manuales, el
        control que justifica la existencia del modelo, saldría inútil.

        Igual que el cierre de la reserva de `mercadopago.payment`: el uuid lo
        pone el navegador, así que no alcanza para autorizar por sí solo. Acá
        la pertenencia es incluso más precisa que cuenta+canal porque la
        aprobación ya guarda el `payment_method_id` exacto de la caja que la
        generó -es el mismo dato que produce `register_manual_approval()`
        sobre `self` (la caja)-, así que basta con exigir que coincida con el
        de esta línea para que una caja no pueda cerrar la aprobación de otra.
        """
        self.ensure_one()
        approval = Approval.search([
            ("pos_payment_uuid", "=", self.mercadopago_uuid),
            ("pos_payment_id", "=", False),
            ("payment_method_id", "=", self.payment_method_id.id),
        ], order="id asc", limit=1)
        if not approval:
            _logger.warning(
                "La línea de pago %s declara el uuid %s pero no hay ninguna "
                "reserva ni aprobación manual de Mercado Pago asociada",
                self.id, self.mercadopago_uuid,
            )
            return
        order = self.pos_order_id
        approval.write({
            "pos_payment_id": self.id,
            "pos_order_id": order.id,
            "pos_session_id": order.session_id.id,
            "amount": self.amount,
        })
        self.write({
            "is_manual_approval": True,
            "manual_reason": approval.reason,
            "manual_approved_by_user_id": approval.user_id.id,
            "manual_approved_at": approval.create_date,
        })
        _logger.info(
            "Aprobación manual de Mercado Pago cerrada sobre la línea de pago %s",
            self.id,
        )
