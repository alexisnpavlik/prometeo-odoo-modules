"""Adaptador de generateContent de Google Gemini."""
import uuid

from . import LlmError
from .http import request_json

_SCHEMA_KEYS = {"type", "properties", "required", "items", "enum", "description"}


def _headers(provider):
    """Cabeceras de autenticación."""
    return {"x-goog-api-key": provider["api_key"], "Content-Type": "application/json"}


def _schema(node):
    """Adapta el JSON Schema al subconjunto de Gemini (tipos en mayúscula)."""
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key not in _SCHEMA_KEYS:
            continue
        if key == "type":
            out[key] = str(value).upper()
        elif key == "properties":
            out[key] = {k: _schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _schema(value)
        else:
            out[key] = value
    return out


def _to_native(messages):
    """Convierte mensajes normalizados a `contents`, emparejando respuestas por nombre."""
    out = []
    for msg in messages:
        if msg["role"] == "user":
            out.append({"role": "user", "parts": [{"text": msg["content"]}]})
        elif msg["role"] == "assistant":
            if msg.get("raw_provider") == "google" and msg.get("raw"):
                out.append({"role": "model", "parts": msg["raw"]})
                continue
            parts = [{"text": msg["content"]}] if msg.get("content") else []
            parts += [{"functionCall": {"name": c["name"], "args": c["arguments"]}} for c in msg.get("tool_calls") or []]
            out.append({"role": "model", "parts": parts or [{"text": "."}]})
        elif msg["role"] == "tool":
            part = {"functionResponse": {"name": msg["name"], "response": {"result": msg["content"]}}}
            if out and out[-1]["role"] == "user" and "functionResponse" in out[-1]["parts"][0]:
                out[-1]["parts"].append(part)
            else:
                out.append({"role": "user", "parts": [part]})
    return out


def chat(provider, model_name, system, messages, tools, timeout):
    """Llama a models/{model}:generateContent y normaliza la respuesta."""
    payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": _to_native(messages)}
    if tools:
        payload["tools"] = [{"functionDeclarations": [
            {"name": t["name"], "description": t["description"], "parameters": _schema(t["parameters"])}
            for t in tools]}]
    url = "%s/models/%s:generateContent" % (provider["base_url"], model_name)
    data = request_json("POST", url, provider["api_key"], timeout, headers=_headers(provider), json=payload)
    candidates = data.get("candidates") or []
    parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if "text" in p and not p.get("thought"))
    calls = [{"id": "call_%s" % uuid.uuid4().hex[:12], "name": p["functionCall"]["name"], "arguments": p["functionCall"].get("args") or {}}
             for i, p in enumerate(p for p in parts if "functionCall" in p)]
    if not text and not calls:
        raise LlmError("El proveedor devolvió una respuesta vacía.")
    usage = data.get("usageMetadata") or {}
    output = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
    return {"text": text, "tool_calls": calls, "input_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": output, "raw": parts, "raw_provider": "google"}


def list_models(provider, timeout=20):
    """GET models, solo los que soportan generateContent."""
    data = request_json("GET", provider["base_url"] + "/models?pageSize=1000", provider["api_key"], timeout,
                        headers=_headers(provider))
    return [{"name": m["name"].split("/", 1)[-1], "label": m.get("displayName") or m["name"]}
            for m in data.get("models") or []
            if "generateContent" in (m.get("supportedGenerationMethods") or [])]
