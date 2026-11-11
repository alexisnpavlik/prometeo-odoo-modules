from odoo import fields, models

from .. import llm

PREFIX = "prometeo_ai_agent."


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_default_model_id = fields.Many2one(
        "prometeo.ai.model", "Modelo por defecto", domain=[("active", "=", True)],
        config_parameter=PREFIX + "default_model_id")
    ai_max_records = fields.Integer("Registros por consulta", default=200, config_parameter=PREFIX + "max_records")
    ai_max_result_chars = fields.Integer("Caracteres por resultado", default=20000,
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
    ai_monthly_cap_usd = fields.Float("Tope mensual (USD)", default=0.0, config_parameter=PREFIX + "monthly_cap_usd")
    ai_digest_hour = fields.Integer("Hora del resumen diario", default=8, config_parameter=PREFIX + "digest_hour")
    ai_dismiss_silence_days = fields.Integer("Días de silencio al descartar", default=30,
                                             config_parameter=PREFIX + "dismiss_silence_days")

    ai_anthropic_key = fields.Char("Clave de Claude (Anthropic)", compute="_compute_ai_keys",
                                   inverse="_inverse_ai_anthropic_key", groups="prometeo_ai_agent.group_admin")
    ai_openai_key = fields.Char("Clave de OpenAI", compute="_compute_ai_keys",
                                inverse="_inverse_ai_openai_key", groups="prometeo_ai_agent.group_admin")
    ai_openai_base_url = fields.Char("URL de OpenAI o compatible", compute="_compute_ai_keys",
                                     inverse="_inverse_ai_openai_base_url", groups="prometeo_ai_agent.group_admin")
    ai_google_key = fields.Char("Clave de Google Gemini", compute="_compute_ai_keys",
                                inverse="_inverse_ai_google_key", groups="prometeo_ai_agent.group_admin")
    ai_active_model_count = fields.Integer("Modelos activos", compute="_compute_ai_keys")

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

    def _compute_ai_keys(self):
        """Lee las claves de los proveedores."""
        for rec in self:
            rec.ai_anthropic_key = rec._ai_provider("anthropic").api_key
            openai = rec._ai_provider("openai")
            rec.ai_openai_key = openai.api_key
            rec.ai_openai_base_url = openai.base_url
            rec.ai_google_key = rec._ai_provider("google").api_key
            rec.ai_active_model_count = self.env["prometeo.ai.model"].sudo().search_count([("active", "=", True)])

    def _inverse_ai_anthropic_key(self):
        for rec in self:
            rec._ai_provider("anthropic").api_key = rec.ai_anthropic_key

    def _inverse_ai_openai_key(self):
        for rec in self:
            rec._ai_provider("openai").api_key = rec.ai_openai_key

    def _inverse_ai_openai_base_url(self):
        for rec in self:
            if rec.ai_openai_base_url:
                rec._ai_provider("openai").base_url = rec.ai_openai_base_url

    def _inverse_ai_google_key(self):
        for rec in self:
            rec._ai_provider("google").api_key = rec.ai_google_key

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

    def action_ai_open_models(self):
        """Lista de modelos para activar y cargar precios."""
        return self.env["ir.actions.act_window"]._for_xml_id("prometeo_ai_agent.action_ai_model")
