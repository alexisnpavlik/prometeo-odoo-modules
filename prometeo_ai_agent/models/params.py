"""Lectura de los parámetros del módulo con sus valores por defecto."""

DEFAULTS = {
    "max_records": 200,
    "max_result_chars": 20000,
    "chat_max_tool_calls": 15,
    "chat_max_seconds": 90,
    "chat_max_concurrent": 2,
    "routine_max_tool_calls": 25,
    "routine_max_seconds": 180,
    "monthly_cap_usd": 0.0,
    "digest_hour": 8,
    "dismiss_silence_days": 30,
}


def get_param(env, key):
    """Devuelve el parámetro prometeo_ai_agent.<key> convertido al tipo de su default."""
    default = DEFAULTS[key]
    raw = env["ir.config_parameter"].sudo().get_param("prometeo_ai_agent." + key)
    try:
        return type(default)(raw) if raw not in (None, False, "") else default
    except (TypeError, ValueError):
        return default
