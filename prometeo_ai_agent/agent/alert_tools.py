"""Herramientas de alertas del agente (solo en rutinas)."""
import json

from .guard import ToolError, check_model, parse_domain

SEVERITIES = ("low", "medium", "high")

ALERT_TOOLS = [
    {"name": "create_alert",
     "description": "Deja una alerta para el dueño del negocio. Respaldala con los registros que leíste "
                    "(model + record_ids) o con un dominio que ya ejecutaste (model + domain).",
     "parameters": {"type": "object", "properties": {
         "key": {"type": "string", "description": "Identificador corto y estable del hallazgo"},
         "title": {"type": "string"},
         "summary": {"type": "string", "description": "Qué pasa, cuánto importa y qué conviene hacer"},
         "severity": {"type": "string", "enum": list(SEVERITIES)},
         "model": {"type": "string"},
         "record_ids": {"type": "array", "items": {"type": "integer"}},
         "domain": {"type": "string", "description": "Dominio en JSON, idéntico a uno ya ejecutado"}},
         "required": ["key", "title", "summary", "severity", "model"]}},
    {"name": "resolve_alert",
     "description": "Cierra una alerta abierta de esta rutina que ya no aplica.",
     "parameters": {"type": "object", "properties": {
         "alert_id": {"type": "integer"}, "reason": {"type": "string"}},
         "required": ["alert_id", "reason"]}},
]


def _create_alert(env, ctx, arguments):
    """Valida el respaldo y crea o actualiza la alerta."""
    routine = ctx.get("routine")
    if not routine:
        raise ToolError("create_alert solo está disponible en rutinas.")
    key = str(arguments.get("key") or "").strip()[:80]
    title = str(arguments.get("title") or "").strip()
    severity = arguments.get("severity")
    if not key or not title:
        raise ToolError("Faltan key o title.")
    if severity not in SEVERITIES:
        raise ToolError("severity debe ser low, medium o high.")
    model = arguments.get("model")
    if not model:
        raise ToolError("Toda alerta necesita respaldo: indicá model y record_ids o domain.")
    check_model(env, model)
    record_ids = arguments.get("record_ids")
    domain_json = arguments.get("domain")
    vals = {"dedup_key": key, "name": title[:200], "summary": str(arguments.get("summary") or ""),
            "severity": severity, "res_model": model, "res_ids": False, "res_domain": False}
    if record_ids:
        try:
            ids = [int(i) for i in record_ids]
        except (TypeError, ValueError):
            raise ToolError("record_ids debe ser una lista de enteros.")
        missing = set(ids) - ctx["seen"].get(model, set())
        if missing:
            raise ToolError("Solo podés citar registros que leíste en esta corrida. No leíste: %s"
                            % sorted(missing)[:20])
        vals["res_ids"] = ids
    elif domain_json:
        domain = parse_domain(env, model, domain_json)
        if json.dumps(domain, sort_keys=True) not in ctx["domains"].get(model, set()):
            raise ToolError("El dominio debe ser idéntico a uno que ejecutaste en esta corrida.")
        vals["res_domain"] = json.dumps(domain)
    else:
        raise ToolError("Toda alerta necesita respaldo: record_ids o domain.")
    alert, status = env["prometeo.ai.alert"]._upsert(routine, routine.sudo().recipient_ids, vals)
    ctx["alerts_touched"].add(alert.id)
    return {"result": status, "alert_id": alert.id}


def _resolve_alert(env, ctx, arguments):
    """Cierra una alerta abierta de la rutina en curso."""
    routine = ctx.get("routine")
    try:
        alert_id = int(arguments.get("alert_id"))
    except (TypeError, ValueError):
        raise ToolError("alert_id inválido.")
    alert = env["prometeo.ai.alert"].sudo().browse(alert_id).exists()
    if not routine or not alert or alert.routine_id != routine or alert.state != "new":
        raise ToolError("No hay una alerta abierta %s de esta rutina." % alert_id)
    alert.write({"state": "resolved", "resolved_note": str(arguments.get("reason") or "")})
    alert.message_post(body="Cerrada por el Agente IA: %s" % (arguments.get("reason") or ""))
    ctx["alerts_touched"].add(alert.id)
    return {"result": "resolved", "alert_id": alert.id}


def _wrap(func):
    """Convierte la función en handler de herramienta: siempre devuelve string JSON."""
    def handler(env, ctx, arguments):
        try:
            if not isinstance(arguments, dict):
                raise ToolError("Los argumentos deben ser un objeto.")
            with env.cr.savepoint():
                result = func(env, ctx, arguments)
        except Exception as e:  # noqa: BLE001 - el error vuelve al modelo
            result = {"error": str(e) or e.__class__.__name__}
        return json.dumps(result, ensure_ascii=False)
    return handler


def alert_tool_handlers():
    """Handlers para pasar como extra_tools a run_agent."""
    return {"create_alert": _wrap(_create_alert), "resolve_alert": _wrap(_resolve_alert)}
