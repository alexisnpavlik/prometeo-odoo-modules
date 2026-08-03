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

    # Piso real del ingestor: `ir.cron` no baja de 1 minuto, así que por más
    # que `poll_interval_seconds` sea 10, la bandeja no se refresca más seguido
    # que eso (ver `mercadopago.account._is_due_for_polling`).
    CRON_FLOOR_SECONDS = 60
    # Cuántos períodos de ingesta sin noticias hacen falta para avisar que la
    # bandeja está desactualizada. Con 1 el aviso se prende y se apaga en cada
    # ciclo -la edad de `last_sync_at` oscila entre 0 y un período completo- y
    # el cajero aprende a ignorarlo justo antes de que la API se caiga en serio.
    STALE_PERIODS = 3

    def _stale_after_seconds(self):
        """Cuánto puede envejecer `last_sync_at` antes de avisar degradación.

        Se mide contra el período real de ingesta -el mayor entre el piso del
        cron y el intervalo configurado-, no contra un número fijo: subir
        `poll_interval_seconds` sin mover esto haría que el aviso quede prendido
        de forma permanente.
        """
        self.ensure_one()
        period = max(self.CRON_FLOOR_SECONDS, self.poll_interval_seconds or 0)
        return period * self.STALE_PERIODS

    def _inbox_ownership_domain(self):
        """Pertenencia: qué pagos son de esta caja, sin mirar la hora.

        Es el criterio que decide de quién es un pago -cuenta, canal y estado-
        y por eso también sirve para autorizar (`_find_inbox_line`). La ventana
        temporal queda deliberadamente afuera: el spec §9 la define como filtro
        de presentación, no como transición de estado. Un pago que envejece
        entre que el cajero lo ve en la lista y hace clic -hasta un intervalo de
        polling de desfasaje- le sigue perteneciendo a esta caja, y tiene que
        poder imputarlo; si no, la única salida que le queda es aprobar sin
        verificar un cobro que sí entró.

        Si esta caja no tiene `mp_pos_id` configurado, la rama del QR no debe
        matchear ningún registro: `("mp_pos_id", "=", False)` calzaría con
        todos los pagos por alias (que también llegan con `mp_pos_id` vacío),
        rompiendo el aislamiento entre cajas por una configuración incompleta.
        """
        self.ensure_one()
        domain = [
            ("account_id", "=", self.mp_account_id.id),
            ("state", "=", "available"),
        ]
        return domain + self._channel_domain()

    def _channel_domain(self):
        """Filtro de canal: QR de esta caja, o alias si está habilitado.

        Separado de `_inbox_ownership_domain()` para poder reusarlo donde hace
        falta acotar por caja/canal sin el `state="available"` de la bandeja
        -por ejemplo, al cerrar en `pos.payment.create()` una reserva que ya
        está en `matched`-. Mismo criterio de aislamiento en los dos lugares:
        si divergiera, una caja podría cerrar la reserva de otra.

        Si esta caja no tiene `mp_pos_id` configurado, la rama del QR no debe
        matchear ningún registro: ver el comentario equivalente en
        `_inbox_ownership_domain()`.
        """
        self.ensure_one()
        qr_leaf = [("mp_pos_id", "=", self.mp_pos_id)] if self.mp_pos_id else [(0, "=", 1)]
        return ["|"] + qr_leaf + [("source", "=", "alias")] \
            if self.accept_alias_payments else qr_leaf

    def _inbox_domain(self):
        """Filtro de presentación: la bandeja de esta caja (§6.2 del spec).

        Pertenencia más la ventana de búsqueda. Sólo lo que se le muestra al
        cajero; para decidir si puede tocar una fila se usa la pertenencia sola.
        """
        self.ensure_one()
        window_start = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=self.search_window_minutes
        )
        return self._inbox_ownership_domain() + [("date_approved", ">=", window_start)]

    def get_mp_inbox(self, amount):
        """Devuelve la bandeja de esta caja para el monto pedido.

        Nunca consulta a Mercado Pago: lee de la base de Odoo. El ingestor
        server-side es el único que habla con la API.
        """
        self.ensure_one()
        self._check_pos_access()
        Inbox = self.env["mercadopago.payment"].sudo()
        available = Inbox.search(self._inbox_domain())

        account = self.mp_account_id.sudo()
        currency = account.company_id.currency_id or self.env.company.currency_id
        tolerance = self.amount_tolerance or 0.0
        # Comparación consciente del redondeo de la moneda: montos crudos en
        # punto flotante no se comparan con <= de forma confiable.
        matching = available.filtered(
            lambda p: currency.compare_amounts(abs(p.amount - amount), tolerance) <= 0
        )
        others = available - matching
        last_sync = account.last_sync_at
        stale = not last_sync or (
            fields.Datetime.now() - last_sync
        ).total_seconds() > self._stale_after_seconds()

        return {
            "matching": [self._serialize_inbox_line(p, amount) for p in matching],
            "others": [self._serialize_inbox_line(p, amount) for p in others],
            "others_count": len(others),
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

    def _find_inbox_line(self, inbox_line_id):
        """Resuelve una fila de la bandeja verificando que sea de esta caja.

        `browse()` a secas alcanza cualquier fila de `mercadopago.payment`, y el
        id llega desde el navegador: un usuario del POS que arme la llamada a
        mano reservaría el pago de otra caja o de otra cuenta. La pertenencia se
        decide con `_inbox_ownership_domain()`.

        Usa la pertenencia y **no** `_inbox_domain()`: la ventana temporal es un
        filtro de presentación, no una condición de autorización. Autorizar con
        ella dejaría inimputable un pago que el cajero tiene en pantalla y que
        envejeció entre el render y el clic.

        No reemplaza al `SELECT ... FOR UPDATE` de `impute()` ni de
        `reserve_for_uuid()`: esto es la puerta de autorización, aquello la
        carrera. Hacen falta las dos.
        """
        self.ensure_one()
        if not isinstance(inbox_line_id, int) or isinstance(inbox_line_id, bool):
            return self.env["mercadopago.payment"].sudo().browse()
        return self.env["mercadopago.payment"].sudo().search(
            self._inbox_ownership_domain() + [("id", "=", inbox_line_id)], limit=1
        )

    @api.model
    def _unavailable_line_error(self):
        """Mensaje único para la fila que ya no está en la bandeja de esta caja."""
        return _(
            "Ese pago ya no está disponible en la bandeja de esta caja. "
            "Actualizá la lista y elegí otro."
        )

    def impute_mp_payment(self, inbox_line_id, pos_payment_id, ambiguous=False):
        """Imputa un pago a una línea. Devuelve el error de carrera si lo hay.

        `inbox_line_id` es el id interno de Odoo del registro de
        `mercadopago.payment` (no el `mp_payment_id` externo de Mercado Pago,
        que es un string): confundirlos imputaría un pago que no es, porque
        Postgres castea el string numérico y `browse()` resolvería cualquier
        registro cuyo id interno coincida.

        Sólo la carrera perdida deliberada de `impute()` (un `UserError` literal)
        se devuelve como resultado de negocio. `AccessError`, `MissingError` y
        `ValidationError` heredan de `UserError` en Odoo pero son bugs o
        problemas de permisos, no una carrera: deben propagarse, no esconderse
        detrás de un mensaje de "ese pago ya fue asignado a otra venta".
        """
        self.ensure_one()
        self._check_pos_access()
        payment = self._find_inbox_line(inbox_line_id)
        if not payment:
            _logger.info(
                "Imputación rechazada: la fila %s no está en la bandeja del método %s",
                inbox_line_id, self.id,
            )
            return {"ok": False, "error": self._unavailable_line_error()}
        pos_payment = self.env["pos.payment"].browse(pos_payment_id)
        try:
            payment.impute(pos_payment, ambiguous=ambiguous)
        except UserError as error:
            if type(error) is not UserError:
                raise
            _logger.info(
                "Imputación rechazada para la línea de bandeja %s: %s",
                inbox_line_id, str(error),
            )
            return {"ok": False, "error": str(error)}
        return {"ok": True, "mp_payment_id": payment.mp_payment_id}

    def impute_mp_payment_by_uuid(self, inbox_line_id, pos_payment_uuid, ambiguous=False):
        """Imputa contra una línea que todavía vive sólo en el navegador.

        La línea de pago se crea en el servidor recién al confirmar la venta, así
        que se guarda el vínculo de forma diferida sobre el uuid de la línea.

        `inbox_line_id` es el id interno de Odoo del registro de
        `mercadopago.payment`, nunca el `mp_payment_id` externo: Postgres castea
        el string numérico y se reservaría un pago arbitrario sin error visible.

        Igual que `impute_mp_payment`, sólo la carrera perdida (un `UserError`
        literal) vuelve como resultado de negocio; `AccessError`, `MissingError`
        y `ValidationError` son bugs o permisos y deben propagarse.
        """
        self.ensure_one()
        self._check_pos_access()
        payment = self._find_inbox_line(inbox_line_id)
        if not payment:
            _logger.info(
                "Reserva rechazada: la fila %s no está en la bandeja del método %s",
                inbox_line_id, self.id,
            )
            return {"ok": False, "error": self._unavailable_line_error()}
        try:
            payment.reserve_for_uuid(pos_payment_uuid, ambiguous=ambiguous)
        except UserError as error:
            if type(error) is not UserError:
                raise
            _logger.info(
                "Reserva rechazada para la línea de bandeja %s: %s",
                inbox_line_id, str(error),
            )
            return {"ok": False, "error": str(error)}
        return {"ok": True, "mp_payment_id": payment.mp_payment_id}

    def revert_mp_reservation_by_uuid(self, pos_payment_uuid):
        """Deshace una reserva hecha durante el cobro, antes de confirmar la venta.

        Es la contraparte de `impute_mp_payment_by_uuid` para el botón de
        deshacer de la imputación automática.

        Tres cierres, porque el uuid lo elige el navegador y no es un secreto:
        se acota a la cuenta de esta caja, al canal/QR de esta caja
        (`_channel_domain()`, el mismo criterio que usa `pos.payment.create()`
        para cerrar la reserva), y a quien hizo la reserva. Sin el último, un
        cajero que leyera el `pos_payment_uuid` de
        una reserva en vuelo de otra caja de la misma cuenta podría liberarla y
        quedársela, dejando la otra línea en `done` contra un pago que ya no
        tiene. `pos_payment_uuid` además dejó de ser legible para el cajero.
        """
        self.ensure_one()
        self._check_pos_access()
        payment = self.env["mercadopago.payment"].sudo().search([
            ("account_id", "=", self.mp_account_id.id),
            ("pos_payment_uuid", "=", pos_payment_uuid),
            ("state", "=", "matched"),
            ("pos_payment_id", "=", False),
        ] + self._channel_domain(), limit=1)
        if not payment:
            return {
                "ok": False,
                "error": _("Esa reserva ya no existe: la venta pudo haberse confirmado."),
            }
        if payment.matched_by_user_id != self.env.user:
            _logger.warning(
                "%s intentó deshacer la reserva %s hecha por %s",
                self.env.user.login, payment.mp_payment_id,
                payment.matched_by_user_id.login,
            )
            return {
                "ok": False,
                "error": _("Esa reserva la hizo otro cajero: no la podés deshacer."),
            }
        payment.revert(reason=_("Deshecho por el cajero antes de confirmar la venta"))
        return {"ok": True}

    def register_manual_approval(self, pos_payment_uuid, reason):
        """Registra una aprobación manual sobre una línea del navegador.

        El uuid se valida igual que en el resto de las entradas por RPC: una
        aprobación creada con uuid vacío -o con algo que no sea un string- no
        la puede cerrar nunca `pos.payment.create()`, y queda para siempre sin
        monto, sin venta y sin sesión, es decir inservible justo para el
        control de §9 que justifica su existencia.
        """
        self.ensure_one()
        self._check_pos_access()
        if not isinstance(pos_payment_uuid, str) or not pos_payment_uuid.strip():
            raise UserError(_("La aprobación manual necesita la línea de cobro."))
        if not isinstance(reason, str) or not reason.strip():
            raise UserError(_("La aprobación manual necesita un motivo."))
        self.env["mercadopago.manual.approval"].sudo().create({
            "payment_method_id": self.id,
            "pos_payment_uuid": pos_payment_uuid,
            "reason": reason.strip(),
            "user_id": self.env.user.id,
        })
        _logger.warning(
            "Cobro aprobado sin verificar el pago por %s sobre la línea %s. Motivo: %s",
            self.env.user.login, pos_payment_uuid, reason.strip(),
        )
        return True
