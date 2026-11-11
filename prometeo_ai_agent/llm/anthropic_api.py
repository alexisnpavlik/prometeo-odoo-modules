"""Adaptador de la API Messages de Anthropic."""
from . import LlmError
from .http import request_json

API_VERSION = "2023-06-01"
MAX_TOKENS = 4096


def _headers(provider):
    """Cabeceras de autenticación."""
    return {"x-api-key": provider["api_key"], "anthropic-version": API_VERSION, "content-type": "application/json"}


def _to_native(messages):
    """Convierte mensajes normalizados al formato Messages (resultados agrupados en un turno user)."""
    out = []
    for msg in messages:
        if msg["role"] == "user":
            out.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            if msg.get("raw_provider") == "anthropic" and msg.get("raw"):
                out.append({"role": "assistant", "content": msg["raw"]})
                continue
            blocks = [{"type": "text", "text": msg["content"]}] if msg.get("content") else []
            blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                       for c in msg.get("tool_calls") or []]
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "."}]})
        elif msg["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": msg["tool_call_id"], "content": msg["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def chat(provider, model_name, system, messages, tools, timeout):
    """Llama a /v1/messages y normaliza la respuesta."""
    payload = {"model": model_name, "max_tokens": MAX_TOKENS, "system": system, "messages": _to_native(messages)}
    if tools:
        payload["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                            for t in tools]
    data = request_json("POST", provider["base_url"] + "/v1/messages", provider["api_key"], timeout,
                        headers=_headers(provider), json=payload)
    content = data.get("content") or []
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    calls = [{"id": b["id"], "name": b["name"], "arguments": b.get("input") or {}}
             for b in content if b.get("type") == "tool_use"]
    if not text and not calls:
        raise LlmError("El proveedor devolvió una respuesta vacía.")
    usage = data.get("usage") or {}
    return {"text": text, "tool_calls": calls, "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0), "raw": content, "raw_provider": "anthropic"}


def list_models(provider, timeout=20):
    """GET /v1/models."""
    data = request_json("GET", provider["base_url"] + "/v1/models?limit=1000", provider["api_key"], timeout,
                        headers=_headers(provider))
    return [{"name": m["id"], "label": m.get("display_name") or m["id"]} for m in data.get("data") or []]
