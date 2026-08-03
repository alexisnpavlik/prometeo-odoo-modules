import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MercadoPagoAccount(models.Model):
    _name = "mercadopago.account"
    _description = "Cuenta de Mercado Pago"

    name = fields.Char(required=True)
    access_token = fields.Char(
        string="Access Token",
        groups="base.group_system",
        help="Token de producción de la cuenta. Nunca sale del servidor.",
    )
    webhook_secret = fields.Char(groups="base.group_system")
    mp_user_id = fields.Char(
        string="Collector ID",
        readonly=True,
        help="Se completa al validar las credenciales. Filtra los cobros propios.",
    )
    mode = fields.Selection(
        [("sandbox", "Sandbox"), ("production", "Producción")],
        default="sandbox",
        required=True,
    )
    active = fields.Boolean(default=False)
    last_validated_at = fields.Datetime(readonly=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_sync_error = fields.Char(readonly=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True
    )

    _sql_constraints = [
        ("mp_user_id_uniq", "unique(mp_user_id, company_id)",
         "Ya existe una cuenta de Mercado Pago con ese Collector ID en esta compañía."),
    ]

    @api.constrains("active", "last_validated_at")
    def _check_validated_before_activation(self):
        """Impide activar una cuenta cuyas credenciales nunca se validaron."""
        for account in self:
            if account.active and not account.last_validated_at:
                raise UserError(_(
                    "Probá la conexión antes de activar la cuenta '%s'.", account.name
                ))

    def action_test_connection(self):
        """Valida las credenciales contra la API y guarda el collector id."""
        self.ensure_one()
        from ..services.mp_client import MercadoPagoClient

        client = MercadoPagoClient(self.sudo().access_token)
        data = client.get_me()
        self.sudo().write({
            "mp_user_id": str(data["id"]),
            "last_validated_at": fields.Datetime.now(),
            "last_sync_error": False,
        })
        _logger.info("Credenciales de Mercado Pago validadas para %s", data.get("nickname"))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _(
                    "Conexión correcta. Collector ID %(uid)s, cuenta %(nick)s.",
                    uid=data["id"], nick=data.get("nickname", ""),
                ),
            },
        }

    def _window_minutes(self):
        """Mayor ventana configurada entre los métodos de pago de esta cuenta."""
        methods = self.env["pos.payment.method"].search([("mp_account_id", "=", self.id)])
        return max(methods.mapped("search_window_minutes") or [5])

    def _poll_interval_seconds(self):
        """Cada cuánto debe consultar esta cuenta, según sus métodos de pago.

        `poll_interval_seconds` se configura por método de pago (spec §5.3) y
        una cuenta puede estar compartida por varias cajas: manda la más
        exigente, porque si una caja pidió refrescar cada 10 segundos, hacerla
        esperar el intervalo de la otra sería incumplir su configuración.

        Sin métodos configurados no hay a quién servirle la bandeja: se usa el
        default del campo.
        """
        self.ensure_one()
        methods = self.env["pos.payment.method"].sudo().search([
            ("use_payment_terminal", "=", "mercadopago_validator"),
            ("mp_account_id", "=", self.id),
        ])
        intervals = [i for i in methods.mapped("poll_interval_seconds") if i and i > 0]
        return min(intervals or [10])

    def _is_due_for_polling(self):
        """Decide si a esta cuenta le toca consultar en esta corrida del cron.

        Spec §6.3: "consulta la ventana a la frecuencia configurada". `ir.cron`
        no baja de 1 minuto de granularidad, así que el intervalo no puede
        vivir en el cron: el cron corre seguido -cada minuto- y cada cuenta
        decide acá si ya pasó su `poll_interval_seconds` desde el último sync.

        La consecuencia, y es la que hay que tener presente en producción: un
        intervalo **menor** a 60 segundos no acelera nada -el piso lo pone el
        cron- pero uno **mayor** sí frena de verdad. Es lo que se necesita para
        no quemar la cuota de la API con muchas cuentas configuradas, sin
        agregar un scheduler propio.
        """
        self.ensure_one()
        if not self.last_sync_at:
            return True
        elapsed = (fields.Datetime.now() - self.last_sync_at).total_seconds()
        return elapsed >= self._poll_interval_seconds()

    def ingest_now(self):
        """Consulta la ventana y vuelca el resultado en la bandeja."""
        from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider
        from ..services.mp_client import MercadoPagoAuthError, MercadoPagoTransientError, MercadoPagoClient

        for account in self:
            provider = MercadoPagoInboxProvider(
                MercadoPagoClient(account.sudo().access_token), account.mp_user_id
            )
            try:
                raw = provider.fetch_payments("NOW-%sMINUTES" % account._window_minutes(), "NOW")
            except MercadoPagoAuthError as error:
                account.sudo().write({"last_sync_error": str(error), "active": False})
                _logger.error("Credenciales rechazadas para la cuenta %s", account.name)
                continue
            except MercadoPagoTransientError as error:
                account.sudo().write({"last_sync_error": str(error)})
                _logger.warning("Bandeja desactualizada para %s: %s", account.name, error)
                continue

            created = self.env["mercadopago.payment"].ingest_raw(account, raw)
            account.sudo().write({
                "last_sync_at": fields.Datetime.now(), "last_sync_error": False,
            })
            if created:
                created._notify_open_sessions()

    def ingest_payment_id(self, payment_id):
        """Trae un pago puntual de la API y lo vuelca en la bandeja.

        Es el camino del webhook: del cuerpo de la notificación sólo se usó el
        identificador, y el dato real se resuelve con credenciales propias.

        Devuelve uno de tres desenlaces, y son distintos a propósito:
        - "created": generó una fila nueva en la bandeja.
        - "existing": el pago ya estaba en la bandeja (reintento de Mercado
          Pago, o el cron llegó primero). Es el camino normal en cada
          notificación duplicada, no una excepción.
        - "failed": no se pudo resolver contra la API, o el pago resuelto no
          es de esta cuenta. El llamador sólo debe probar otra cuenta activa
          ante "failed": tratar "existing" igual que "failed" haría que cada
          notificación duplicada le pegue a la API con las credenciales de
          todas las demás cuentas configuradas, preguntando por un pago ajeno.
        """
        self.ensure_one()
        from ..services.inbox_provider_mercadopago import MercadoPagoInboxProvider
        from ..services.mp_client import MercadoPagoClient, MercadoPagoError, MercadoPagoTransientError

        provider = MercadoPagoInboxProvider(
            MercadoPagoClient(self.sudo().access_token), self.mp_user_id
        )
        try:
            raw = provider.get_payment(payment_id)
        except (MercadoPagoError, MercadoPagoTransientError) as error:
            _logger.warning("No se pudo resolver el pago %s: %s", payment_id, error)
            return "failed"

        Inbox = self.env["mercadopago.payment"]
        created = Inbox.ingest_raw(self, [raw])
        if created:
            created._notify_open_sessions()
            return "created"
        if Inbox.search_count([("mp_payment_id", "=", str(payment_id))]):
            return "existing"
        return "failed"

    @api.model
    def cron_ingest_payments(self):
        """Cron del ingestor. Corre seguido; cada cuenta decide si le toca.

        Sólo trabaja si hay una sesión de POS abierta, con el mismo predicado
        que `_notify_open_sessions()`: `state != "closed"`, no `state ==
        "opened"`. El `state` de una sesión pasa por "opening_control" hasta
        que el cajero confirma el conteo de apertura, y es el criterio que usa
        el propio Odoo en `_compute_current_session`. Con el predicado
        divergente, una caja abierta sin confirmar el conteo recibía avisos por
        bus de una bandeja que el ingestor no estaba llenando.

        La frecuencia por cuenta la resuelve `_is_due_for_polling()`: el cron
        es el reloj, no el intervalo (ver ahí el detalle del piso de 1 minuto).
        """
        open_sessions = self.env["pos.session"].search_count([("state", "!=", "closed")])
        if not open_sessions:
            return
        accounts = self.search([("active", "=", True)])
        due = accounts.filtered(lambda a: a._is_due_for_polling())
        if not due:
            return
        due.ingest_now()
