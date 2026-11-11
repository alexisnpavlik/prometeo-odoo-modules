"""Bucle del agente: alterna llamadas al modelo y herramientas con topes de llamadas y tiempo."""
import time

from .. import llm
from . import tools

INCOMPLETE_TEXT = "No llegué a terminar el análisis dentro del límite configurado."
LIMIT_NOTICE = ("Llegaste al límite de consultas de esta corrida. No uses más herramientas: "
                "respondé ahora con lo que ya sabés.")
LIMIT_ERROR = '{"error": "límite de llamadas alcanzado"}'
MIN_SECONDS_LEFT = 5
CALL_TIMEOUT = 60


def _assistant_message(response):
    """Mensaje assistant normalizado a partir de la respuesta del proveedor."""
    return {"role": "assistant", "content": response["text"], "tool_calls": response["tool_calls"],
            "raw": response["raw"], "raw_provider": response["raw_provider"]}


def run_agent(env, ai_model, system, messages, tool_defs, ctx, max_tool_calls, max_seconds, extra_tools=None):
    """Corre el agente hasta que responde sin pedir herramientas o choca con un límite.

    `llm.chat` se llama por el atributo del módulo para que los tests lo puedan parchear.
    Los errores del proveedor (llm.LlmError) se propagan.
    """
    extra_tools = extra_tools or {}
    provider = ai_model.sudo().provider_id._get_credentials()
    model_name = ai_model.sudo().name
    history = list(messages)
    new_messages = []
    totals = {"input_tokens": 0, "output_tokens": 0}
    calls_done = 0
    deadline = time.monotonic() + max_seconds

    def call(extra=None):
        remaining = deadline - time.monotonic()
        response = llm.chat(provider, model_name, system, history + (extra or []), tool_defs,
                            max(1, int(min(CALL_TIMEOUT, remaining))))
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
            return result(response["text"], "done")
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
