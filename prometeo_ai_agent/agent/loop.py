"""Bucle del agente: alterna llamadas al modelo y herramientas con topes de llamadas y tiempo."""
import json
import time

from .. import llm
from . import numbers, tools

INCOMPLETE_TEXT = "No llegué a terminar el análisis dentro del límite configurado."
LIMIT_NOTICE = ("Llegaste al límite de consultas de esta corrida. No uses más herramientas: "
                "respondé ahora con lo que ya sabés.")
VERIFY_NOTICE = ("Estos números de tu respuesta no salen de ninguna consulta ni cuenta: %s. "
                 "Verificalos con las herramientas (usá calculate para las cuentas) o sacalos. "
                 "No inventes números. Respondé de nuevo completo.")
UNVERIFIED_NOTE = "\n\n(Algunos números no se pudieron verificar con los datos consultados: %s)"
LIMIT_ERROR = '{"error": "límite de llamadas alcanzado"}'
MIN_SECONDS_LEFT = 5
CALL_TIMEOUT = 60


def _assistant_message(response):
    """Mensaje assistant normalizado a partir de la respuesta del proveedor."""
    return {"role": "assistant", "content": response["text"], "tool_calls": response["tool_calls"],
            "raw": response["raw"], "raw_provider": response["raw_provider"]}


STEP_VERBS = {
    "list_models": "Buscando dónde están los datos",
    "get_fields": "Revisando los campos de",
    "search_read": "Leyendo",
    "read_group": "Calculando totales en",
    "search_count": "Contando en",
    "create_alert": "Dejando una alerta",
    "resolve_alert": "Cerrando una alerta",
}


def describe_step(env, name, arguments, content):
    """Texto corto de un paso para mostrar en vivo: qué consultó y cuánto encontró."""
    verb = STEP_VERBS.get(name, name)
    model = (arguments or {}).get("model") if isinstance(arguments, dict) else None
    if model and name not in ("create_alert",):
        label = env["ir.model"].sudo()._get(model).name if model in env else model
        verb = "%s %s" % (verb, label)
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return verb
    if "error" in data:
        return "%s: no se pudo, lo intento de otra forma" % verb
    for key in ("records", "groups", "models", "fields"):
        if key in data:
            return "%s: %s resultados" % (verb, len(data[key]))
    if "count" in data:
        return "%s: %s registros" % (verb, data["count"])
    return verb


def run_agent(env, ai_model, system, messages, tool_defs, ctx, max_tool_calls, max_seconds, extra_tools=None,
              on_step=None):
    """Corre el agente hasta que responde sin pedir herramientas o choca con un límite.

    `llm.chat` se llama por el atributo del módulo para que los tests lo puedan parchear.
    Los errores del proveedor (llm.LlmError) se propagan.
    """
    extra_tools = extra_tools or {}
    known = ctx.setdefault("numbers", set())
    numbers.source_numbers([system] + [m.get("content") for m in messages], known)
    verified_once = False
    provider = ai_model.sudo().provider_id._get_credentials()
    model_name = ai_model.sudo().name
    history = list(messages)
    new_messages = []
    totals = {"input_tokens": 0, "output_tokens": 0}
    calls_done = 0
    deadline = time.monotonic() + max_seconds

    def call(extra=None):
        remaining = deadline - time.monotonic()
        try:
            response = llm.chat(provider, model_name, system, history + (extra or []), tool_defs,
                                max(1, int(min(CALL_TIMEOUT, remaining))))
        except Exception as e:
            e.usage = dict(totals, tool_calls=calls_done)
            raise
        totals["input_tokens"] += response["input_tokens"]
        totals["output_tokens"] += response["output_tokens"]
        return response

    def result(text, status):
        return {"text": text or INCOMPLETE_TEXT, "new_messages": new_messages, "tool_calls": calls_done,
                "status": status, **totals}

    while True:
        if deadline - time.monotonic() <= MIN_SECONDS_LEFT:
            return result("", "incomplete")
        response = call()
        message = _assistant_message(response)
        history.append(message)
        new_messages.append(message)
        if not response["tool_calls"]:
            missing = numbers.unsupported(response["text"], known)
            if missing and not verified_once and deadline - time.monotonic() > MIN_SECONDS_LEFT:
                verified_once = True
                new_messages.pop()
                history.append({"role": "user", "content": VERIFY_NOTICE % ", ".join(missing)})
                continue
            text = response["text"]
            if missing:
                text += UNVERIFIED_NOTE % ", ".join(missing)
                new_messages[-1] = dict(new_messages[-1], content=text)
            return result(text, "done")
        for tool_call in response["tool_calls"]:
            if calls_done >= max_tool_calls:
                content = LIMIT_ERROR
            else:
                handler = extra_tools.get(tool_call["name"])
                if handler:
                    content = handler(env, ctx, tool_call["arguments"])
                else:
                    content = tools.execute_tool(env, ctx, tool_call["name"], tool_call["arguments"])
                calls_done += 1
                if on_step:
                    try:
                        on_step(describe_step(env, tool_call["name"], tool_call["arguments"], content))
                    except Exception:  # noqa: BLE001 - el aviso en vivo nunca corta la corrida
                        pass
            try:
                numbers.source_numbers(json.loads(content), known)
            except (TypeError, ValueError):
                pass
            tool_message = {"role": "tool", "tool_call_id": tool_call["id"], "name": tool_call["name"],
                            "content": content}
            history.append(tool_message)
            new_messages.append(tool_message)
        if calls_done >= max_tool_calls:
            if deadline - time.monotonic() <= MIN_SECONDS_LEFT:
                return result("", "incomplete")
            final = call([{"role": "user", "content": LIMIT_NOTICE}])
            if final["text"]:
                message = _assistant_message(dict(final, tool_calls=[], raw=None, raw_provider=None))
                new_messages.append(message)
            return result(final["text"], "incomplete")
