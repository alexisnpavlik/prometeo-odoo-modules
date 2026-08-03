import logging

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import UserError

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
    pos_payment_uuid = fields.Char(
        readonly=True, index=True,
        help="uuid de la línea del navegador que reservó el pago durante el cobro.",
    )
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
        el mismo dato es como aparecen las inconsistencias irreproducibles. Con
        el webhook conviviendo con el cron, dos llamadas pueden hacer el search
        de existencia al mismo tiempo, no encontrar nada, e intentar crear la
        misma fila: la que pierde la carrera contra la restricción única de
        mp_payment_id degrada con gracia en vez de propagar el IntegrityError.
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
            try:
                with self.env.cr.savepoint():
                    created |= self.create(values)
            except psycopg2.IntegrityError:
                # Otro llamador (cron o webhook) ganó la carrera y ya lo creó.
                # Releemos el registro ganador y seguimos con ese: la llamada
                # perdedora debe terminar con el mismo resultado que la ganadora,
                # no comportarse como si no hubiera pasado nada. No se suma a
                # `created`: quien lo creó ya se encargó de notificar.
                winner = self.search([("mp_payment_id", "=", values["mp_payment_id"])], limit=1)
                _logger.info(
                    "Carrera de ingesta en el pago %s: ya lo creó otro proceso, se sigue con ese registro",
                    values["mp_payment_id"],
                )
                if winner and winner.state == "available":
                    winner.write(self._values_without_state(values))

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

    def impute(self, pos_payment, ambiguous=False):
        """Vincula este pago con una línea de cobro del POS, de forma definitiva.

        Toma la fila con SELECT ... FOR UPDATE antes de decidir: dos cajeros
        pueden hacer clic con milisegundos de diferencia sobre la misma lista.
        El índice único parcial actúa como red final si el bloqueo falla.
        """
        self.ensure_one()
        pos_payment.ensure_one()
        # cr.execute no flushea: sin esto se bloquea y se lee una fila vieja, y
        # un revert() previo en esta misma transacción daría un rechazo falso.
        self.flush_recordset(["state"])
        self.env.cr.execute(
            "SELECT state FROM mercadopago_payment WHERE id = %s FOR UPDATE", (self.id,)
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "available":
            raise UserError(_(
                "Ese pago ya fue asignado a otra venta. Actualizá la lista y elegí otro."
            ))
        linked = pos_payment.mercadopago_payment_id
        if linked and linked.id != self.id:
            # Sin este chequeo el índice único parcial tira un IntegrityError
            # crudo en el flush y al cajero le llega una traza técnica.
            raise UserError(_(
                "Esa línea de cobro ya tiene asignado el pago de Mercado Pago %s.",
                linked.mp_payment_id,
            ))

        order = pos_payment.pos_order_id
        difference = pos_payment.amount - self.amount
        self.write({
            "state": "matched",
            "pos_payment_id": pos_payment.id,
            "pos_order_id": order.id,
            "pos_session_id": order.session_id.id,
            "matched_by_user_id": self.env.user.id,
            "matched_at": fields.Datetime.now(),
            "amount_difference": difference,
            "ambiguous_pick": ambiguous,
        })
        pos_payment.write({"mercadopago_payment_id": self.id})
        _logger.info(
            "Pago %s imputado a la línea %s por %s",
            self.mp_payment_id, pos_payment.id, self.env.user.login,
        )
        return True

    def reserve_for_uuid(self, pos_payment_uuid, ambiguous=False):
        """Reserva el pago para una línea que aún no existe en el servidor.

        Durante el cobro la línea vive sólo en el navegador: la orden se crea al
        confirmar la venta. La reserva se apoya en el uuid de esa línea y se
        completa después, al crearse el `pos.payment`.

        Usa el mismo bloqueo de fila que impute(): la carrera entre dos cajeros
        ocurre acá, antes de que exista el pos.payment. Igual que allá, el
        flush previo es obligatorio: cr.execute no flushea y sin él se bloquea
        y se lee una fila vieja.
        """
        self.ensure_one()
        if not pos_payment_uuid:
            raise ValueError("reserve_for_uuid necesita el uuid de la línea de cobro")
        self.flush_recordset(["state"])
        self.env.cr.execute(
            "SELECT state FROM mercadopago_payment WHERE id = %s FOR UPDATE", (self.id,)
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "available":
            raise UserError(_(
                "Ese pago ya fue asignado a otra venta. Actualizá la lista y elegí otro."
            ))
        self.write({
            "state": "matched",
            "pos_payment_uuid": pos_payment_uuid,
            "matched_by_user_id": self.env.user.id,
            "matched_at": fields.Datetime.now(),
            "ambiguous_pick": ambiguous,
        })
        _logger.info(
            "Pago %s reservado para la línea %s por %s",
            self.mp_payment_id, pos_payment_uuid, self.env.user.login,
        )
        self._notify_open_sessions()
        return True

    def revert(self, reason=None):
        """Devuelve el pago a la bandeja. Queda registrado en el chatter del pedido.

        Es la operación inversa sobre la misma fila, así que se toma con el mismo
        bloqueo que impute(): sin él, un revert contra una imputación concurrente
        sale como error de serialización crudo en vez de un mensaje legible.
        """
        self.ensure_one()
        self.flush_recordset(["state"])
        self.env.cr.execute(
            "SELECT state FROM mercadopago_payment WHERE id = %s FOR UPDATE", (self.id,)
        )
        row = self.env.cr.fetchone()
        if not row or row[0] != "matched":
            raise UserError(_("Sólo se puede revertir un pago imputado."))
        order = self.pos_order_id
        line = self.pos_payment_id
        self.write({
            "state": "available", "pos_payment_id": False, "pos_order_id": False,
            "pos_session_id": False, "matched_by_user_id": False, "matched_at": False,
            "amount_difference": 0.0, "ambiguous_pick": False,
            # Una reserva por uuid que sobrevive al revert dejaría al pago
            # esperando una línea que ya no lo reclama.
            "pos_payment_uuid": False,
        })
        if line:
            # El índice único vive del lado de mercadopago_payment.pos_payment_id:
            # si no se limpia también acá, la línea vieja sigue contando el cobro.
            line.write({"mercadopago_payment_id": False})
        _logger.info(
            "Pago %s revertido por %s. Motivo: %s",
            self.mp_payment_id, self.env.user.login, reason or "sin motivo",
        )
        if order:
            order.message_post(body=_(
                "Se revirtió la imputación del pago de Mercado Pago %(mp)s. Motivo: %(reason)s",
                mp=self.mp_payment_id, reason=reason or _("sin motivo"),
            ))
        return True

    def _notify_open_sessions(self):
        """Avisa por bus a las cajas con sesión abierta que la bandeja cambió.

        El bus de Odoo 18 no tiene canal global para el POS: pos.bus.mixin
        publica en el canal privado de cada pos.config (token propio por
        config). Hay que resolver qué configs están afectadas por cada pago
        e iterarlas notificando una por una.

        El criterio de pertenencia tiene que ser el mismo que usa
        `_inbox_domain()` en pos.payment.method: un método de este módulo
        pertenece a un pago si su cuenta coincide y, según el canal, su
        mp_pos_id es el del QR o tiene habilitado accept_alias_payments. Si
        divergiera, una caja podría recibir un aviso de un pago que después
        no ve en su lista (o al revés).

        `current_session_state` de pos.config es un campo computado sin
        store=True: no es buscable (`search()` sobre un compute sin store
        levanta ValueError en Odoo 18). Además su valor es literalmente el
        `state` de la sesión, y ese state pasa por "opening_control" antes
        de llegar a "opened" (recién al confirmar el conteo de apertura, no
        al sólo abrir la interfaz). Lo que necesitamos -una caja con un
        diálogo de cobro en uso- es "hay una sesión de esta caja que no está
        cerrada", el mismo criterio que usa pos.config para su propio
        current_session_id/has_active_session (state != "closed"), así que
        se resuelve vía pos.session con ese filtro en vez de state="opened".

        El llamador (`ingest_now()`) suele activar esto sobre un lote de
        varios pagos nuevos de la misma corrida de polling, y lo habitual es
        que compartan cuenta y QR. Por eso se agrupa antes de consultar: una
        sola búsqueda de métodos y de sesiones por grupo (account_id,
        mp_pos_id) o (account_id, alias), en vez de repetirla por pago. Un
        lote de N pagos del mismo QR queda en un número constante de
        consultas, no en 2N.
        """
        Session = self.env["pos.session"].sudo()
        qr_groups = {}
        alias_groups = {}
        for payment in self:
            if payment.source == "qr":
                if not payment.mp_pos_id:
                    # Anomalía de datos: un pago QR sin mp_pos_id no debe
                    # matchear por accidente los métodos sin QR configurado.
                    _logger.warning(
                        "Pago QR %s sin mp_pos_id: no se puede resolver a qué caja avisar",
                        payment.mp_payment_id,
                    )
                    continue
                qr_groups.setdefault((payment.account_id.id, payment.mp_pos_id), []).append(payment)
            else:
                alias_groups.setdefault(payment.account_id.id, []).append(payment)

        for (account_id, mp_pos_id), payments in qr_groups.items():
            methods = self.env["pos.payment.method"].sudo().search([
                ("mp_account_id", "=", account_id),
                ("mp_pos_id", "=", mp_pos_id),
            ])
            self._notify_configs_for_methods(methods, payments, Session)

        for account_id, payments in alias_groups.items():
            methods = self.env["pos.payment.method"].sudo().search([
                ("mp_account_id", "=", account_id),
                ("accept_alias_payments", "=", True),
            ])
            self._notify_configs_for_methods(methods, payments, Session)

        return True

    def _notify_configs_for_methods(self, methods, payments, Session):
        """Notifica por bus, una vez por config y por pago, a las cajas de `methods`.

        `methods` y `payments` ya vienen agrupados por (cuenta, canal) desde
        `_notify_open_sessions()`: acá sólo se resuelven las configs con
        sesión abierta para ese grupo y se emite el evento por cada pago.
        """
        if not methods:
            return
        sessions = Session.search([
            ("state", "!=", "closed"),
            ("config_id.payment_method_ids", "in", methods.ids),
        ])
        for config in sessions.config_id:
            for payment in payments:
                config._notify("MERCADOPAGO_INBOX_UPDATED", {
                    "config_id": config.id,
                    "mp_payment_id": payment.mp_payment_id,
                    "amount": payment.amount,
                    "state": payment.state,
                })
