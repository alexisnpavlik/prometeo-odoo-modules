"""Herramientas de lectura del agente. Corren como el usuario de `env`: nunca sudo."""
import ast
import json
import math
import operator

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
                    "groupby admite 'fecha:month' (day, week, month, quarter, year) y solo campos directos. "
                    "having filtra por los totales (ej. '[[\"quantity:sum\", \"<=\", 0]]'); order ordena "
                    "(ej. 'quantity:sum asc'); limit corta (por defecto 50). total_groups dice cuántos grupos hay "
                    "en total: usalo para contar sin traer todos.",
     "parameters": {"type": "object", "properties": {
         "model": {"type": "string"},
         "domain": {"type": "string"},
         "groupby": {"type": "array", "items": {"type": "string"}},
         "aggregates": {"type": "array", "items": {"type": "string"}},
         "having": {"type": "string", "description": "Filtro sobre agregados en JSON"},
         "order": {"type": "string"},
         "limit": {"type": "integer"}},
         "required": ["model", "domain", "groupby", "aggregates"]}},
    {"name": "calculate",
     "description": "Calcula cuentas exactas: sumas, restas, multiplicaciones, divisiones, porcentajes y "
                    "variaciones. Usala SIEMPRE en vez de hacer cuentas de cabeza. Mandá varias cuentas juntas. "
                    "Admite + - * / ( ), round(x, decimales), abs, min, max.",
     "parameters": {"type": "object", "properties": {
         "expressions": {"type": "array", "items": {"type": "string"},
                         "description": "Ej. ['1532.5 * 12', '(18390 - 15000) / 15000 * 100']"}},
         "required": ["expressions"]}},
    {"name": "search_count",
     "description": "Cuenta los registros que cumplen un dominio.",
     "parameters": {"type": "object", "properties": {"model": {"type": "string"}, "domain": {"type": "string"}},
                    "required": ["model", "domain"]}},
]


def new_context(routine=None):
    """Estado de una corrida: ids y dominios leídos, para validar el respaldo de las alertas."""
    return {"seen": {}, "domains": {}, "routine": routine, "alerts_touched": set(), "numbers": set()}


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


HAVING_OPERATORS = ("=", "!=", "<", "<=", ">", ">=")
GROUP_LIMIT = 50


def _read_group(env, ctx, model, domain, groupby, aggregates, having=None, order=None, limit=None):
    """Agrega con el ORM (aplica permisos y reglas). Admite filtro sobre los totales, orden y límite."""
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
    having_list = []
    if having:
        try:
            having_list = json.loads(having) if isinstance(having, str) else having
        except ValueError:
            raise ToolError("having no es JSON válido.")
        for leaf in having_list:
            if (not isinstance(leaf, list) or len(leaf) != 3 or leaf[0] not in aggregates
                    or leaf[1] not in HAVING_OPERATORS or isinstance(leaf[2], (list, dict))):
                raise ToolError("having admite [agregado, operador, número] con un agregado pedido en aggregates.")
    order_spec = None
    if order:
        parts = str(order).split()
        if len(parts) > 2 or parts[0] not in groupby + aggregates or (len(parts) == 2 and parts[1].lower() not in ("asc", "desc")):
            raise ToolError("order debe ser un groupby o un agregado pedido, con asc o desc.")
        order_spec = " ".join(parts)
    limit = min(int(limit or GROUP_LIMIT), get_param(env, "max_records"))
    rows = Model._read_group(domain, groupby, aggregates, having=having_list, order=order_spec, limit=limit)
    total = len(Model._read_group(domain, groupby, [], having=having_list)) if groupby else len(rows)
    keys = groupby + aggregates
    groups = [{key: _plain(value) for key, value in zip(keys, row)} for row in rows]
    _remember_domain(ctx, model, domain)
    return {"groups": groups, "total_groups": total, "shown": len(groups)}


def _search_count(env, ctx, model, domain):
    """Cuenta registros."""
    Model = check_model(env, model)
    domain = parse_domain(env, model, domain)
    count = Model.search_count(domain)
    _remember_domain(ctx, model, domain)
    return {"count": count}


_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max}
MAX_VALUE = 1e18


def _eval_node(node):
    """Evalúa un árbol aritmético seguro: solo números, operadores y round/abs/min/max."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _eval_node(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ToolError("Potencia demasiado grande.")
        return _BINOPS[type(node.op)](left, right)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS
            and not node.keywords):
        return _FUNCS[node.func.id](*[_eval_node(arg) for arg in node.args])
    raise ToolError("Solo se admiten números, + - * / ( ) y round, abs, min, max.")


def _calculate(env, ctx, expressions):
    """Cuentas exactas; cada resultado queda registrado para el verificador."""
    if isinstance(expressions, str):
        expressions = [expressions]
    results = []
    for expr in list(expressions)[:50]:
        try:
            value = _eval_node(ast.parse(str(expr), mode="eval"))
            if not math.isfinite(value) or abs(value) > MAX_VALUE:
                raise ToolError("Resultado fuera de rango.")
            value = round(float(value), 10)
            ctx.setdefault("numbers", set()).add(value)
            results.append({"expr": expr, "value": value})
        except ZeroDivisionError:
            results.append({"expr": expr, "error": "División por cero."})
        except (ToolError, SyntaxError, TypeError, ValueError) as e:
            results.append({"expr": expr, "error": str(e) or "Expresión inválida."})
    return {"results": results}


_HANDLERS = {
    "calculate": _calculate,
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


from .alert_tools import ALERT_TOOLS, alert_tool_handlers  # noqa: E402,F401
