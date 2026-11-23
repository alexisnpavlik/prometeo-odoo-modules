from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .. import llm

PREFIX = "prometeo_ai_agent."


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_default_model_id = fields.Many2one(
        "prometeo.ai.model", "Modelo por defecto", domain=[("active", "=", True)],
        config_parameter=PREFIX + "default_model_id")
    ai_max_records = fields.Integer("Registros por consulta", default=200, config_parameter=PREFIX + "max_records")
    ai_max_result_chars = fields.Integer("Caracteres por resultado", default=8000,
                                         config_parameter=PREFIX + "max_result_chars")
    ai_chat_max_tool_calls = fields.Integer("Llamadas por turno de chat", default=15,
                                            config_parameter=PREFIX + "chat_max_tool_calls")
    ai_chat_max_seconds = fields.Integer("Segundos por turno de chat", default=90,
                                         config_parameter=PREFIX + "chat_max_seconds")
    ai_chat_max_concurrent = fields.Integer("Chats simultáneos", default=2,
                                            config_parameter=PREFIX + "chat_max_concurrent")
    ai_routine_max_tool_calls = fields.Integer("Llamadas por corrida de rutina", default=25,
                                               config_parameter=PREFIX + "routine_max_tool_calls")
    ai_routine_max_seconds = fields.Integer("Segundos por corrida de rutina", default=180,
                                            config_parameter=PREFIX + "routine_max_seconds")
    ai_monthly_cap_usd = fields.Float("Tope mensual (USD)", default=5.0, config_parameter=PREFIX + "monthly_cap_usd")
    ai_digest_hour = fields.Integer("Hora del resumen diario", default=8, config_parameter=PREFIX + "digest_hour")
    ai_support_contact = fields.Char("Contacto de soporte", config_parameter=PREFIX + "support_contact",
                                     help="Se muestra cuando el servicio de IA falla. Ej.: Alexis, 11 5555-5555")
    ai_dismiss_silence_days = fields.Integer("Días de silencio al descartar", default=30,
                                             config_parameter=PREFIX + "dismiss_silence_days")

    # Las claves no pasan por compute/inverse: el onchange inicial del formulario no corre computes sin
    # dependencias, el campo llegaba vacío y al guardar pisaba la clave real. Se leen en get_values y se
    # guardan en set_values; la clave nunca viaja al navegador y el campo vacío significa "no cambiar".
    ai_anthropic_key = fields.Char("Nueva clave de Claude (Anthropic)", groups="prometeo_ai_agent.group_admin")
    ai_openai_key = fields.Char("Nueva clave de OpenAI", groups="prometeo_ai_agent.group_admin")
    ai_openai_base_url = fields.Char("URL de OpenAI o compatible", groups="prometeo_ai_agent.group_admin")
    ai_google_key = fields.Char("Nueva clave de Google Gemini", groups="prometeo_ai_agent.group_admin")
    ai_active_model_count = fields.Integer("Modelos activos", readonly=True)
    ai_month_cost = fields.Float("Gasto del mes (USD)", readonly=True, digits=(12, 2))
    ai_anthropic_status = fields.Char(readonly=True)
    ai_anthropic_ok = fields.Boolean(readonly=True)
    ai_anthropic_has_key = fields.Boolean(readonly=True)
    ai_openai_status = fields.Char(readonly=True)
    ai_openai_ok = fields.Boolean(readonly=True)
    ai_openai_has_key = fields.Boolean(readonly=True)
    ai_google_status = fields.Char(readonly=True)
    ai_google_ok = fields.Boolean(readonly=True)
    ai_google_has_key = fields.Boolean(readonly=True)

    def _ai_provider(self, provider_type):
        """Proveedor de ese tipo (el que tenga clave primero); lo crea si no existe."""
        Provider = self.env["prometeo.ai.provider"].sudo()
        providers = Provider.search([("provider_type", "=", provider_type)])
        provider = providers.filtered("api_key")[:1] or providers[:1]
        if not provider:
            labels = dict(Provider._fields["provider_type"].selection)
            provider = Provider.create({"name": labels[provider_type], "provider_type": provider_type,
                                        "base_url": llm.DEFAULT_BASE_URLS[provider_type]})
        return provider

    @api.model
    def _ai_is_admin(self):
        """Solo el administrador del agente ve y guarda las claves."""
        return self.env.su or self.env.user.has_group("prometeo_ai_agent.group_admin")

    @api.model
    def _ai_key_status(self, provider):
        """Texto de estado de un proveedor: clave enmascarada más el resultado de la última prueba."""
        if not provider.api_key:
            return _("Sin clave cargada.")
        masked = _("Clave cargada (termina en %s).", provider.api_key.strip()[-4:])
        return "%s %s" % (masked, provider.check_message or _("Sin probar."))

    @api.model
    def get_values(self):
        """Carga estado de proveedores, modelos activos y gasto. Los campos de clave quedan vacíos."""
        res = super().get_values()
        if not self._ai_is_admin():
            return res
        for ptype in ("anthropic", "openai", "google"):
            provider = self._ai_provider(ptype)
            res["ai_%s_status" % ptype] = self._ai_key_status(provider)
            res["ai_%s_ok" % ptype] = provider.check_state == "ok"
            res["ai_%s_has_key" % ptype] = bool(provider.api_key)
        res["ai_openai_base_url"] = self._ai_provider("openai").base_url
        res["ai_active_model_count"] = self.env["prometeo.ai.model"].sudo().search_count([("active", "=", True)])
        res["ai_month_cost"] = self.env["prometeo.ai.run"].sudo()._month_cost()
        return res

    def set_values(self):
        """Guarda solo las claves escritas (vacío = conservar) y la URL si cambió."""
        super().set_values()
        if not self._ai_is_admin():
            return
        for rec in self:
            for ptype in ("anthropic", "openai", "google"):
                key = (rec["ai_%s_key" % ptype] or "").strip()
                provider = rec._ai_provider(ptype)
                if key and key != provider.api_key:
                    provider.api_key = key
            url = (rec.ai_openai_base_url or "").strip()
            openai = rec._ai_provider("openai")
            if url and url != openai.base_url:
                openai.base_url = url

    def action_ai_clear_key(self):
        """Borra la clave del proveedor indicado en el contexto (único modo de dejarlo sin clave)."""
        ptype = self.env.context.get("ai_provider_type")
        if ptype not in ("anthropic", "openai", "google") or not self._ai_is_admin():
            raise UserError(_("Proveedor inválido."))
        self._ai_provider(ptype).api_key = False
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def _ai_fetch(self, provider_type):
        """Guarda los ajustes y trae los modelos del proveedor."""
        self.execute()
        return self._ai_provider(provider_type).action_fetch_models()

    def action_ai_fetch_models_anthropic(self):
        return self._ai_fetch("anthropic")

    def action_ai_fetch_models_openai(self):
        return self._ai_fetch("openai")

    def action_ai_fetch_models_google(self):
        return self._ai_fetch("google")

    def action_ai_open_usage(self):
        """Pantalla de consumo mensual."""
        return self.env["ir.actions.actions"]._for_xml_id("prometeo_ai_agent.action_ai_usage")

    def action_ai_open_models(self):
        """Lista de modelos para activar y cargar precios."""
        return self.env["ir.actions.act_window"]._for_xml_id("prometeo_ai_agent.action_ai_model")
