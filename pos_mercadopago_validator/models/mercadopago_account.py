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
