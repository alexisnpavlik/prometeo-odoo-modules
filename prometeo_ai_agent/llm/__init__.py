"""Capa de proveedores de IA: una interfaz común para Anthropic, OpenAI y Google.

Formato normalizado (ver el plan):
    proveedor:   {"type", "api_key", "base_url"}
    herramienta: {"name", "description", "parameters": JSON Schema}
    mensaje:     {"role": "user"|"assistant"|"tool", "content", ...}
    respuesta:   {"text", "tool_calls", "input_tokens", "output_tokens", "raw", "raw_provider"}
"""

DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta",
}


class LlmError(Exception):
    """Falla al hablar con el proveedor. `status` es el código HTTP si lo hubo."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


from . import anthropic_api, google_api, openai_api, prices  # noqa: E402

_ADAPTERS = {"anthropic": anthropic_api, "openai": openai_api, "google": google_api}


def _adapter(provider):
    """Devuelve el módulo adaptador del tipo de proveedor."""
    try:
        return _ADAPTERS[provider["type"]]
    except KeyError:
        raise LlmError("Tipo de proveedor desconocido: %s" % provider.get("type"))


def chat(provider, model_name, system, messages, tools, timeout):
    """Envía la conversación al proveedor y devuelve la respuesta normalizada."""
    return _adapter(provider).chat(provider, model_name, system, messages, tools, timeout)


def list_models(provider, timeout=20):
    """Lista los modelos de chat que ofrece el proveedor: [{"name", "label"}]."""
    return _adapter(provider).list_models(provider, timeout)
