from datetime import datetime

import pytz

from odoo import api, fields, models

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
        cap = get_param(self.env, "monthly_cap_usd")
        return bool(cap) and self._month_cost() >= cap
