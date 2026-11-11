"""Qué puede leer el agente: lista negra de modelos y campos, y validación de dominios."""
import json
import re

BLOCKED_MODELS = frozenset({
    "prometeo.ai.provider", "prometeo.ai.conversation", "prometeo.ai.message",
    "ir.config_parameter", "res.users.apikeys", "ir.cron", "ir.attachment", "mail.message",
    "ir.model.access", "ir.rule",
})
USER_FIELDS = frozenset({"id", "name", "login", "company_id", "display_name"})
SECRET_FIELD_RE = re.compile(r"(password|passwd|secret|token|api_?key|private_?key|_pass$)", re.I)
LOGIC_OPERATORS = ("&", "|", "!")
SUBDOMAIN_OPERATORS = ("any", "not any")
ORDER_RE = re.compile(r"^\s*([\w.]+)(\s+(asc|desc))?(\s+nulls\s+(first|last))?\s*$", re.I)


class ToolError(Exception):
    """Pedido inválido o no permitido; el mensaje vuelve al modelo."""


def check_model(env, model):
    """Valida que el modelo exista, no esté bloqueado y el usuario lo pueda leer."""
    if not isinstance(model, str) or model not in env:
        raise ToolError("El modelo %r no existe." % (model,))
    Model = env[model]
    if model in BLOCKED_MODELS:
        raise ToolError("El modelo %s no está disponible para el agente." % model)
    if Model._abstract or Model._transient:
        raise ToolError("El modelo %s no guarda datos." % model)
    if not Model.has_access("read"):
        raise ToolError("Sin permiso de lectura sobre %s." % model)
    return Model


def check_field(env, model, name):
    """Valida un campo directo del modelo y lo devuelve."""
    field = env[model]._fields.get(name)
    if field is None:
        raise ToolError("El campo %s no existe en %s." % (name, model))
    if SECRET_FIELD_RE.search(name):
        raise ToolError("El campo %s no está disponible para el agente." % name)
    if model == "res.users" and name not in USER_FIELDS:
        raise ToolError("En res.users solo se pueden usar: %s." % ", ".join(sorted(USER_FIELDS)))
    if field.type == "binary":
        raise ToolError("Los campos binarios no están disponibles (%s)." % name)
    if field.relational and field.comodel_name in BLOCKED_MODELS:
        raise ToolError("El campo %s apunta a un modelo no disponible." % name)
    if not field.is_accessible(env):
        raise ToolError("Sin permiso para el campo %s." % name)
    return field


def check_field_path(env, model, path):
    """Valida un camino a.b.c relación por relación. Devuelve el modelo del último campo."""
    if not isinstance(path, str) or not path:
        raise ToolError("Nombre de campo inválido: %r" % (path,))
    current = model
    parts = path.split(".")
    for index, name in enumerate(parts):
        field = check_field(env, current, name)
        if index < len(parts) - 1:
            if not field.relational:
                raise ToolError("%s no es una relación en %s." % (name, current))
            current = field.comodel_name
            check_model(env, current)
    return current, field


def _check_domain(env, model, domain):
    """Recorre el dominio y valida cada hoja (incluidos subdominios any/not any)."""
    if not isinstance(domain, list):
        raise ToolError("El dominio debe ser una lista.")
    for item in domain:
        if isinstance(item, str):
            if item not in LOGIC_OPERATORS:
                raise ToolError("Operador lógico inválido: %r" % item)
            continue
        if not isinstance(item, list) or len(item) != 3 or not isinstance(item[0], str):
            raise ToolError("Cada condición debe ser [campo, operador, valor]: %r" % (item,))
        path, operator, value = item
        if not isinstance(operator, str):
            raise ToolError("Operador inválido: %r" % (operator,))
        if path in ("1", "0"):  # hojas TRUE/FALSE de Odoo
            continue
        comodel, field = check_field_path(env, model, path)
        if operator.lower() in SUBDOMAIN_OPERATORS:
            if not field.relational:
                raise ToolError("%s solo se usa con relaciones." % operator)
            check_model(env, field.comodel_name)
            _check_domain(env, field.comodel_name, value)


def parse_domain(env, model, domain_json):
    """Convierte el dominio (string JSON) en lista y lo valida."""
    if isinstance(domain_json, list):
        domain = domain_json
    else:
        try:
            domain = json.loads(domain_json or "[]")
        except (TypeError, ValueError):
            raise ToolError("El dominio no es JSON válido.")
    _check_domain(env, model, domain)
    return domain


def check_order(env, model, order):
    """Valida un orden 'campo [asc|desc], ...'."""
    if not order:
        return None
    for chunk in str(order).split(","):
        match = ORDER_RE.match(chunk)
        if not match:
            raise ToolError("Orden inválido: %r" % chunk)
        check_field_path(env, model, match.group(1))
    return order
