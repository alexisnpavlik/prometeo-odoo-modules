from datetime import datetime

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from .params import get_param

DEFAULT_TZ = "America/Argentina/Buenos_Aires"


class PrometeoAiRun(models.Model):
    _name = "prometeo.ai.run"
    _description = "Corrida del agente IA (consumo)"
    _order = "create_date desc, id desc"

    kind = fields.Selection([("routine", "Rutina"), ("chat", "Chat")], "Tipo", required=True)
    routine_id = fields.Many2one("prometeo.ai.routine", "Rutina", ondelete="set null", index=True)
    user_id = fields.Many2one("res.users", "Usuario")
    ai_model_id = fields.Many2one("prometeo.ai.model", "Modelo", ondelete="set null")
    model_name = fields.Char("Id del modelo")
    provider_type = fields.Char("Proveedor")
    input_tokens = fields.Integer("Tokens de entrada")
    output_tokens = fields.Integer("Tokens de salida")
    cost = fields.Float("Costo (USD)", digits=(12, 6))
    price_known = fields.Boolean("Con precio")
    duration = fields.Float("Duración (s)", digits=(8, 1))
    tool_calls = fields.Integer("Llamadas a herramientas")
    status = fields.Selection([("done", "Completa"), ("incomplete", "Incompleta"), ("error", "Error"),
                               ("skipped_cap", "Omitida por tope")], "Estado", required=True)
    error = fields.Text("Error")

    @api.model
    def _log(self, kind, ai_model, result, *, routine=None, user=None, status, error=None, duration=0.0):
        """Registra una corrida y calcula su costo con el precio del modelo."""
        result = result or {}
        input_tokens = int(result.get("input_tokens") or 0)
        output_tokens = int(result.get("output_tokens") or 0)
        ai_model = ai_model.sudo() if ai_model else ai_model
        price_known = bool(ai_model and ai_model.price_known)
        cost = (input_tokens / 1e6 * ai_model.price_input + output_tokens / 1e6 * ai_model.price_output) \
            if price_known else 0.0
        return self.sudo().create({
            "kind": kind, "routine_id": routine.id if routine else False, "user_id": user.id if user else False,
            "ai_model_id": ai_model.id if ai_model else False, "model_name": ai_model.name if ai_model else False,
            "provider_type": ai_model.provider_type if ai_model else False,
            "input_tokens": input_tokens, "output_tokens": output_tokens, "cost": cost,
            "price_known": price_known, "duration": duration, "tool_calls": int(result.get("tool_calls") or 0),
            "status": status, "error": error})

    @api.model
    def _month_bounds(self, year=None, month=None):
        """Inicio y fin (UTC, naive) del mes calendario en la zona horaria de la empresa."""
        tz = pytz.timezone(self.env.company.partner_id.tz or DEFAULT_TZ)
        now_local = datetime.now(pytz.utc).astimezone(tz)
        year, month = year or now_local.year, month or now_local.month
        start = tz.localize(datetime(year, month, 1))
        end = tz.localize(datetime(year + (month == 12), month % 12 + 1, 1))
        return (start.astimezone(pytz.utc).replace(tzinfo=None), end.astimezone(pytz.utc).replace(tzinfo=None))

    @api.model
    def _month_cost(self, year=None, month=None):
        """Gasto del mes en USD (solo modelos con precio)."""
        start, end = self._month_bounds(year, month)
        groups = self.sudo()._read_group([("create_date", ">=", start), ("create_date", "<", end)],
                                         aggregates=["cost:sum"])
        return (groups[0][0] or 0.0) if groups else 0.0

    @api.model
    def _cap_reached(self):
        """True si hay tope mensual y el gasto del mes lo alcanzó."""
        cap = get_param(self.env, "monthly_cap_usd") or 5.0
        return self._month_cost() >= cap

    @api.model
    def get_quota_status(self):
        """Porcentaje usado del tope del mes, sin montos (lo ve cualquier usuario del agente)."""
        if not self.env.user.has_group("prometeo_ai_agent.group_user"):
            raise AccessError(_("Sin acceso al Agente IA."))
        cap = get_param(self.env, "monthly_cap_usd") or 5.0
        percent = min(100, int(round(self.sudo()._month_cost() / cap * 100)))
        level = "over" if percent >= 100 else ("warn" if percent >= 80 else "ok")
        return {"percent": percent, "level": level}

    @api.model
    def get_usage_summary(self, year, month):
        """Resumen del mes para la pantalla Consumo (solo administradores del agente)."""
        if not self.env.user.has_group("prometeo_ai_agent.group_admin"):
            raise AccessError(_("Solo los administradores del agente ven el consumo."))
        start, end = self._month_bounds(int(year), int(month))
        runs = self.sudo().search([("create_date", ">=", start), ("create_date", "<", end)])

        def rows(key_func):
            table = {}
            for run in runs:
                name = key_func(run)
                row = table.setdefault(name, {"name": name, "runs": 0, "input_tokens": 0, "output_tokens": 0,
                                              "cost": 0.0})
                row["runs"] += 1
                row["input_tokens"] += run.input_tokens
                row["output_tokens"] += run.output_tokens
                row["cost"] += run.cost
            return sorted(table.values(), key=lambda r: (-r["cost"], r["name"]))

        return {
            "cost": sum(runs.mapped("cost")),
            "cap": get_param(self.env, "monthly_cap_usd"),
            "unpriced_runs": len(runs.filtered(lambda r: not r.price_known and r.status != "skipped_cap"
                                               and (r.input_tokens or r.output_tokens))),
            "by_routine": rows(lambda r: _("Chat") if r.kind == "chat" else (r.routine_id.name or _("Rutina borrada"))),
            "by_model": rows(lambda r: r.ai_model_id.display_name or r.model_name or _("Sin modelo")),
            "start": fields.Datetime.to_string(start),
        }
