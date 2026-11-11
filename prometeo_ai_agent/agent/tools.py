"""Herramientas de lectura del agente. Corren como el usuario de `env`: nunca sudo."""
import json

from ..models.params import get_param
from .guard import BLOCKED_MODELS, SECRET_FIELD_RE, USER_FIELDS, ToolError, check_field, check_model, \
    check_order, parse_domain

AGGREGATES = ("sum", "avg", "min", "max", "count", "count_distinct")
DEFAULT_LIMIT = 80
TRUNCATED = "...[recortado]"

READ_TOOLS = [
    {"name": "list_models",
     "description": "Lista los modelos de Odoo que se pueden consultar (nombre técnico y descripción). "
                    "Usá 'search' para filtrar por palabra (ej. 'stock', 'factura').",
     "parameters": {"type": "object", "properties": {"search": {"type": "string", "description": "Texto a buscar"}}}},
    {"name": "get_fields",
     "description": "Campos de un modelo: nombre, tipo, etiqueta y modelo relacionado.",
     "parameters": {"type": "object", "properties": {"model": {"type": "string"}}, "required": ["model"]}},
    {"name": "search_read",
     "description": "Lee registros. 'domain' es un dominio de Odoo como string JSON, ej. "
                    "'[[\"state\", \"=\", \"assigned\"]]'. Pedí solo los campos necesarios.",
     "parameters": {"type": "object", "properties": {
         "model": {"type": "string"},
         "domain": {"type": "string", "description": "Dominio Odoo en JSON; '[]' para todos"},
         "fields": {"type": "array", "items": {"type": "string"}},
         "order": {"type": "string", "description": "Ej. 'date desc'"},
         "limit": {"type": "integer"},
         "offset": {"type": "integer"}},
         "required": ["model", "domain", "fields"]}},
    {"name": "read_group",
     "description": "Agrega registros (suma, promedio, mínimo, máximo, conteo) agrupando por campos. "
                    "Usalo para todo número total en vez de sumar a mano. aggregates: ['campo:sum', 'id:count']. "
                    "groupby admite 'fecha:month' (day, week, month, quarter, year).",
     "parameters": {"type": "object", "properties": {
         "model": {"type": "string"},
         "domain": {"type": "string"},
         "groupby": {"type": "array", "items": {"type": "string"}},
         "aggregates": {"type": "array", "items": {"type": "string"}}},
         "required": ["model", "domain", "groupby", "aggregates"]}},
    {"name": "search_count",
     "description": "Cuenta los registros que cumplen un dominio.",
     "parameters": {"type": "object", "properties": {"model": {"type": "string"}, "domain": {"type": "string"}},
                    "required": ["model", "domain"]}},
]


def new_context(routine=None):
    """Estado de una corrida: ids y dominios leídos, para validar el respaldo de las alertas."""
    return {"seen": {}, "domains": {}, "routine": routine, "alerts_touched": set()}


def _remember_domain(ctx, model, domain):
    """Registra un dominio ejecutado (serializado de forma estable)."""
    ctx["domains"].setdefault(model, set()).add(json.dumps(domain, sort_keys=True))


def _plain(value):
    """Convierte valores del ORM en algo serializable."""
    if hasattr(value, "_name") and hasattr(value, "ids"):
        return [[r.id, r.display_name] for r in value]
    return value


def _list_models(env, ctx, search=None):
    """Modelos legibles y no bloqueados, filtrados por texto."""
    domain = [("transient", "=", False)]
    if search:
        domain += ["|", ("model", "ilike", search), ("name", "ilike", search)]
    out = []
    for rec in env["ir.model"].sudo().search(domain, order="model"):
        if rec.model in BLOCKED_MODELS or rec.model not in env:
            continue
        Model = env[rec.model]
        if Model._abstract or not Model.has_access("read"):
            continue
        out.append({"model": rec.model, "name": rec.name})
        if len(out) >= 100:
            break
    return {"models": out}


def _get_fields(env, ctx, model):
    """Campos almacenados y permitidos del modelo."""
    check_model(env, model)
    out = []
    for name, field in env[model]._fields.items():
        if not field.store or field.type == "binary" or SECRET_FIELD_RE.search(name):
            continue
        if model == "res.users" and name not in USER_FIELDS:
            continue
        if field.relational and field.comodel_name in BLOCKED_MODELS:
            continue
        if not field.is_accessible(env):
            continue
        item = {"name": name, "type": field.type, "string": field.string}
        if field.relational:
            item["relation"] = field.comodel_name
        if field.type == "selection" and isinstance(field.selection, list):
            item["selection"] = field.selection
        out.append(item)
    return {"fields": out}


def _search_read(env, ctx, model, domain, fields, order=None, limit=None, offset=0):
    """Lee registros con tope de cantidad y registra lo leído."""
    Model = check_model(env, model)
    domain = parse_domain(env, model, domain)
    if not fields or not isinstance(fields, list):
        raise ToolError("Indicá la lista de campos a leer.")
    for name in fields:
        if "." in str(name):
            raise ToolError("search_read no admite campos con punto; usá el campo relacionado o otra consulta.")
        check_field(env, model, name)
    order = check_order(env, model, order)
    cap = get_param(env, "max_records")
    limit = min(int(limit or DEFAULT_LIMIT), cap)
    records = Model.search(domain, order=order, limit=limit, offset=int(offset or 0))
    rows = records.read(list(fields))
    ctx["seen"].setdefault(model, set()).update(records.ids)
    for name in fields:
        field = Model._fields[name]
        if field.type == "many2one":
            ctx["seen"].setdefault(field.comodel_name, set()).update(
                row[name][0] for row in rows if row.get(name))
    _remember_domain(ctx, model, domain)
    return {"records": rows, "count": len(rows), "limit": limit}


def _read_group(env, ctx, model, domain, groupby, aggregates):
    """Agrega con el ORM (aplica permisos y reglas)."""
    Model = check_model(env, model)
    domain = parse_domain(env, model, domain)
    groupby = list(groupby or [])
    aggregates = list(aggregates or [])
    for spec in groupby:
        check_field(env, model, str(spec).split(":")[0])
    for spec in aggregates:
        name, _sep, agg = str(spec).partition(":")
        if agg not in AGGREGATES:
            raise ToolError("Agregado inválido %r; usá %s." % (spec, ", ".join(AGGREGATES)))
        check_field(env, model, name)
    if not aggregates:
        aggregates = ["__count"]
    rows = Model._read_group(domain, groupby, aggregates, limit=get_param(env, "max_records"))
    keys = groupby + aggregates
    groups = [{key: _plain(value) for key, value in zip(keys, row)} for row in rows]
    _remember_domain(ctx, model, domain)
    return {"groups": groups}


def _search_count(env, ctx, model, domain):
    """Cuenta registros."""
    Model = check_model(env, model)
    domain = parse_domain(env, model, domain)
    count = Model.search_count(domain)
    _remember_domain(ctx, model, domain)
    return {"count": count}


_HANDLERS = {
    "list_models": _list_models,
    "get_fields": _get_fields,
    "search_read": _search_read,
    "read_group": _read_group,
    "search_count": _search_count,
}


def execute_tool(env, ctx, name, arguments):
    """Ejecuta una herramienta y devuelve siempre un string JSON (con 'error' si falló)."""
    handler = _HANDLERS.get(name)
    try:
        if handler is None:
            raise ToolError("Herramienta desconocida: %s" % name)
        if not isinstance(arguments, dict):
            raise ToolError("Los argumentos deben ser un objeto.")
        with env.cr.savepoint():
            result = handler(env, ctx, **arguments)
    except TypeError as e:
        result = {"error": "Argumentos inválidos para %s: %s" % (name, e)}
    except Exception as e:  # noqa: BLE001 - todo error vuelve al modelo
        result = {"error": str(e) or e.__class__.__name__}
    text = json.dumps(result, default=str, ensure_ascii=False)
    max_chars = get_param(env, "max_result_chars")
    if len(text) > max_chars:
        text = text[:max_chars] + TRUNCATED
    return text
