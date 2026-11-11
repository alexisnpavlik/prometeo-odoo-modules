"""Adaptador de Chat Completions de OpenAI (y servicios compatibles)."""
import json
import uuid

from . import LlmError
from .http import request_json


def _headers(provider):
    """Cabeceras de autenticación."""
    return {"Authorization": "Bearer %s" % provider["api_key"], "Content-Type": "application/json"}


def _to_native(system, messages):
    """Convierte mensajes normalizados al formato Chat Completions."""
    out = [{"role": "system", "content": system}]
    for msg in messages:
        if msg["role"] == "user":
            out.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            native = {"role": "assistant", "content": msg.get("content") or None}
            if msg.get("tool_calls"):
                native["tool_calls"] = [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                                        for c in msg["tool_calls"]]
            out.append(native)
        elif msg["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": msg["tool_call_id"], "content": msg["content"]})
    return out


def _parse_args(raw):
    """Los argumentos llegan como string JSON; si no parsean, van vacíos."""
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def chat(provider, model_name, system, messages, tools, timeout):
    """Llama a /chat/completions y normaliza la respuesta."""
    payload = {"model": model_name, "messages": _to_native(system, messages)}
    if tools:
        payload["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]
    data = request_json("POST", provider["base_url"] + "/chat/completions", provider["api_key"], timeout,
                        headers=_headers(provider), json=payload)
    choices = data.get("choices") or []
    message = (choices[0].get("message") or {}) if choices else {}
    text = message.get("content") or ""
    calls = [{"id": c.get("id") or "call_%s" % uuid.uuid4().hex[:12], "name": c["function"]["name"],
              "arguments": _parse_args(c["function"].get("arguments"))}
             for i, c in enumerate(message.get("tool_calls") or [])]
    if not text and not calls:
        raise LlmError("El proveedor devolvió una respuesta vacía.")
    usage = data.get("usage") or {}
    return {"text": text, "tool_calls": calls, "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0), "raw": None, "raw_provider": "openai"}


def list_models(provider, timeout=20):
    """GET /models."""
    data = request_json("GET", provider["base_url"] + "/models", provider["api_key"], timeout,
                        headers=_headers(provider))
    return [{"name": m["id"], "label": m["id"]} for m in data.get("data") or []]
