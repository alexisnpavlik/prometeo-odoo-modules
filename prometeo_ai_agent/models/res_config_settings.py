from odoo import fields, models

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
