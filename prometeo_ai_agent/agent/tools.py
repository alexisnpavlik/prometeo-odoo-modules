"""Herramientas de lectura del agente. Corren como el usuario de `env`: nunca sudo."""
import ast
import json
import math
import operator

from odoo import fields as odoo_fields

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
    {"name": "sum_expression",
     "description": "Suma una cuenta por registro y la agrupa: para totales que multiplican campos, que read_group "
                    "no puede hacer. Ej.: valor del stock a precio de venta y a costo por sucursal: model "
                    "'stock.quant', domain '[[\"location_id.usage\", \"=\", \"internal\"], [\"quantity\", \">\", 0]]', "
                    "groupby ['company_id'], expressions ['quantity * sale_price(product_id)', "
                    "'quantity * cost(product_id)']. Admite campos numéricos (también con punto por relaciones "
                    "many2one, ej. 'product_id.weight'), números, + - * / ( ), y dos funciones sobre un campo de "
                    "producto: sale_price(campo) = precio de venta unitario según la lista de precios de las cajas "
                    "de la sucursal del registro; cost(campo) = costo unitario cargado en el producto para esa sucursal. products_at_zero cuenta productos con precio o costo en 0 (sin cargar): avisalo junto al total. groupby: campos "
                    "directos (sin ':mes'); vacío para un total general.",
     "parameters": {"type": "object", "properties": {
         "model": {"type": "string"},
         "domain": {"type": "string"},
         "groupby": {"type": "array", "items": {"type": "string"}},
         "expressions": {"type": "array", "items": {"type": "string"}},
         "limit": {"type": "integer"}},
         "required": ["model", "domain", "groupby", "expressions"]}},
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


EXPR_FUNCS = ("sale_price", "cost")
EXPR_NUMERIC = ("integer", "float", "monetary")
EXPR_MAX_ROWS = 200000
EXPR_BATCH = 5000


def _expr_path(node):
    """Name o Attribute → 'campo.subcampo'."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return "%s.%s" % (_expr_path(node.value), node.attr)
    raise ToolError("Se esperaba un nombre de campo.")


def _check_expr_path(env, model, path, final_types):
    """Valida un camino: intermedios many2one y el último del tipo pedido."""
    current = model
    parts = path.split(".")
    for index, name in enumerate(parts):
        field = check_field(env, current, name)
        if index < len(parts) - 1:
            if field.type != "many2one":
                raise ToolError("%s no es una relación simple (many2one) en %s." % (name, current))
            current = field.comodel_name
            check_model(env, current)
    if field.type not in final_types and getattr(field, "comodel_name", None) not in final_types:
        raise ToolError("%s no es un campo válido acá (tipo %s)." % (path, field.type))
    return field


def _compile_expression(env, model, expression):
    """Valida la expresión y devuelve (árbol, caminos numéricos, {(función, camino de producto)})."""
    try:
        tree = ast.parse(str(expression), mode="eval")
    except SyntaxError:
        raise ToolError("Expresión inválida: %r" % expression)
    paths, calls = set(), set()

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return walk(node.operand)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            walk(node.left)
            return walk(node.right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in EXPR_FUNCS or len(node.args) != 1 or node.keywords:
                raise ToolError("Funciones admitidas: sale_price(campo_producto), cost(campo_producto).")
            path = _expr_path(node.args[0])
            _check_expr_path(env, model, path, ("product.product",))
            if node.func.id == "cost":
                check_field(env, "product.product", "standard_price")
            calls.add((node.func.id, path))
            return
        if isinstance(node, (ast.Name, ast.Attribute)):
            path = _expr_path(node)
            _check_expr_path(env, model, path, EXPR_NUMERIC)
            paths.add(path)
            return
        raise ToolError("Solo se admiten campos, números, + - * / ( ), sale_price() y cost().")

    walk(tree)
    return tree, paths, calls


def _resolve_path(record, path):
    """Valor del camino en un registro (vacío = False)."""
    value = record
    for name in path.split("."):
        value = value[name]
    return value


def _branch_pricelist(env, company):
    """Lista de precios de la sucursal: la más usada por sus cajas; si no hay, la primera de la empresa."""
    if "pos.config" in env:
        counts = env["pos.config"].sudo()._read_group(
            [("company_id", "=", company.id), ("pricelist_id", "!=", False)], ["pricelist_id"], ["__count"])
        if counts:
            return max(counts, key=lambda row: (row[1], -row[0].id))[0]
    return env["product.pricelist"].sudo().search(
        [("company_id", "in", [company.id, False])], order="sequence, id", limit=1)


def _product_prices(env, func, company, products):
    """{product_id: precio} de venta (lista de la sucursal) o costo (en la sucursal)."""
    if func == "cost":
        return {p.id: p.standard_price for p in products.with_company(company)}
    pricelist = _branch_pricelist(env, company)
    if not pricelist:
        return {p.id: p.lst_price for p in products.with_company(company)}
    return _fast_pricelist_prices(pricelist.with_company(company), products.with_company(company))


def _fast_pricelist_prices(pricelist, products):
    """Igual que pricelist._compute_price_rule(products, 1) pero indexando las reglas.

    Odoo prueba cada producto contra todas las reglas (O(productos × reglas)): con listas de 20.000
    reglas tarda minutos. Acá se mantiene el orden de reglas de Odoo y _is_applicable_for, solo que
    cada producto se prueba contra sus candidatas (variante, plantilla, categoría, globales).
    """
    date = odoo_fields.Datetime.now()
    currency = pricelist.currency_id or pricelist.env.company.currency_id
    rules = pricelist._get_applicable_rules(products, date)
    by_variant, by_tmpl, by_categ, global_rules = {}, {}, [], []
    for index, rule in enumerate(rules):
        if rule.applied_on == "0_product_variant":
            by_variant.setdefault(rule.product_id.id, []).append(index)
        elif rule.applied_on == "1_product":
            by_tmpl.setdefault(rule.product_tmpl_id.id, []).append(index)
        elif rule.applied_on == "2_product_category":
            by_categ.append((index, rule.categ_id))
        else:
            global_rules.append(index)
    empty = pricelist.env["product.pricelist.item"]
    prices = {}
    for product in products:
        candidates = by_variant.get(product.id, []) + by_tmpl.get(product.product_tmpl_id.id, []) + global_rules
        path = product.categ_id.parent_path or ""
        candidates += [i for i, categ in by_categ if product.categ_id == categ or path.startswith(categ.parent_path)]
        rule = empty
        for index in sorted(candidates):
            if rules[index]._is_applicable_for(product, 1.0):
                rule = rules[index]
                break
        prices[product.id] = rule._compute_price(product, 1.0, product.uom_id, date=date, currency=currency)
    return prices


def _eval_expression(node, record, values, prices, company_id):
    """Evalúa el árbol ya validado para un registro."""
    if isinstance(node, ast.Expression):
        return _eval_expression(node.body, record, values, prices, company_id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp):
        value = _eval_expression(node.operand, record, values, prices, company_id)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left = _eval_expression(node.left, record, values, prices, company_id)
        right = _eval_expression(node.right, record, values, prices, company_id)
        if isinstance(node.op, ast.Div):
            return left / right if right else 0.0
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.Call):
        path = _expr_path(node.args[0])
        product = values[path]
        return prices.get((node.func.id, company_id), {}).get(product.id, 0.0) if product else 0.0
    return values[_expr_path(node)] or 0.0


def _sum_expression(env, ctx, model, domain, groupby, expressions, limit=None):
    """Suma expresiones por registro, agrupadas. Corre como el usuario; solo los precios usan sudo."""
    Model = check_model(env, model)
    domain = parse_domain(env, model, domain)
    groupby = list(groupby or [])
    for name in groupby:
        if ":" in str(name) or "." in str(name):
            raise ToolError("groupby admite solo campos directos; para fechas por mes usá read_group.")
        check_field(env, model, name)
    if isinstance(expressions, str):
        expressions = [expressions]
    expressions = list(expressions or [])[:5]
    if not expressions:
        raise ToolError("Indicá al menos una expresión.")
    compiled = [_compile_expression(env, model, expr) for expr in expressions]
    paths = set().union(*(c[1] for c in compiled))
    calls = set().union(*(c[2] for c in compiled))
    records = Model.search(domain)
    if len(records) > EXPR_MAX_ROWS:
        raise ToolError("Son %s registros; acotá el dominio (máximo %s)." % (len(records), EXPR_MAX_ROWS))
    has_company = "company_id" in Model._fields
    default_company = env.company

    # Precios de producto por sucursal, calculados en lote.
    prices = {}
    if calls:
        wanted = {}
        for rec in records:
            company = (rec.company_id if has_company else None) or default_company
            for _func, path in calls:
                product = _resolve_path(rec, path)
                if product:
                    wanted.setdefault(company, set()).add(product.id)
        for company, product_ids in wanted.items():
            products = env["product.product"].sudo().browse(sorted(product_ids))
            for func in {c[0] for c in calls}:
                prices[(func, company.id)] = _product_prices(env, func, company, products)

    groups = {}
    for start in range(0, len(records), EXPR_BATCH):
        for rec in records[start:start + EXPR_BATCH]:
            company = (rec.company_id if has_company else None) or default_company
            values = {path: _resolve_path(rec, path) for path in paths}
            values.update({path: _resolve_path(rec, path) for _func, path in calls})
            key = tuple(_plain(rec[name]) if rec._fields[name].relational else rec[name] for name in groupby)
            key = tuple(tuple(map(tuple, k)) if isinstance(k, list) else k for k in key)
            bucket = groups.setdefault(key, [0.0] * len(compiled) + [0])
            for index, (tree, _paths, _calls) in enumerate(compiled):
                bucket[index] += _eval_expression(tree, rec, values, prices, company.id)
            bucket[-1] += 1
    rows = []
    for key, bucket in groups.items():
        row = {name: (list(map(list, value)) if isinstance(value, tuple) else value) for name, value in zip(groupby, key)}
        for expr, total in zip(expressions, bucket[:-1]):
            row[expr] = round(total, 2)
        row["records"] = bucket[-1]
        rows.append(row)
    rows.sort(key=lambda r: r[expressions[0]], reverse=True)
    limit = min(int(limit or GROUP_LIMIT), get_param(env, "max_records"))
    totals = {expr: round(sum(r[expr] for r in rows), 2) for expr in expressions}
    result = {"groups": rows[:limit], "total_groups": len(rows), "shown": min(len(rows), limit),
              "totals": totals, "records": len(records)}
    if calls:
        # Productos en cero: costo o precio sin cargar. El agente debe avisarlo junto al total.
        zero = {}
        for (func, _cid), product_prices in prices.items():
            zero[func] = zero.get(func, 0) + sum(1 for value in product_prices.values() if not value)
        result["products_at_zero"] = zero
    if calls and any(c[0] == "sale_price" for c in calls):
        companies = {c[1] for c in prices if c[0] == "sale_price"}
        result["price_lists"] = {env["res.company"].browse(cid).name: _branch_pricelist(
            env, env["res.company"].browse(cid)).display_name or "precio de la ficha" for cid in companies}
    _remember_domain(ctx, model, domain)
    return result


_HANDLERS = {
    "calculate": _calculate,
    "list_models": _list_models,
    "get_fields": _get_fields,
    "search_read": _search_read,
    "read_group": _read_group,
    "search_count": _search_count,
    "sum_expression": _sum_expression,
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
