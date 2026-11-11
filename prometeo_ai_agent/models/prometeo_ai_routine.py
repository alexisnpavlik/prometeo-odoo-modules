import json
import logging
import time
from datetime import datetime, timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import config as tools_config

from .. import llm
from ..agent import loop, prompts, tools
from .params import get_param

_logger = logging.getLogger(__name__)

DEFAULT_TZ = "America/Argentina/Buenos_Aires"
DISPATCH_BUDGET_SECONDS = 600
MAX_FAILURES = 3
MAX_INCOMPLETE = 3
INTERVALS = [("minutes", "Minutos"), ("hours", "Horas"), ("days", "Días"), ("weeks", "Semanas")]
FREQUENCY_FIELDS = {"interval_number", "interval_type", "run_hour", "run_as_user_id"}


class PrometeoAiRoutine(models.Model):
    _name = "prometeo.ai.routine"
    _description = "Rutina del agente IA"
    _order = "name"

    name = fields.Char("Nombre", required=True)
    prompt = fields.Text("Instrucción", help="Qué tiene que revisar el agente, en lenguaje natural.")
    active = fields.Boolean("Activa", default=True)
    paused = fields.Boolean("Pausada", readonly=True, copy=False,
                            help="Se pausa sola tras 3 errores seguidos. Reanudala desde el botón.")
    interval_number = fields.Integer("Cada", default=1, required=True)
    interval_type = fields.Selection(INTERVALS, "Unidad", default="days", required=True)
    run_hour = fields.Float("Hora", default=8.0, help="Hora local de ejecución (días y semanas).")
    next_run = fields.Datetime("Próxima ejecución", copy=False)
    last_run = fields.Datetime("Última ejecución", readonly=True, copy=False)
    last_status = fields.Selection([("done", "Completa"), ("incomplete", "Incompleta"), ("error", "Error"),
                                    ("skipped_cap", "Omitida por tope")], "Último estado", readonly=True, copy=False)
    run_as_user_id = fields.Many2one("res.users", "Ejecutar como", required=True,
                                     default=lambda self: self.env.user, context={"active_test": False},
                                     help="El agente lee con los permisos de este usuario.")
    company_ids = fields.Many2many("res.company", "prometeo_ai_routine_company_rel", "routine_id", "company_id",
                                   "Empresas", default=lambda self: self.env.company)
    recipient_ids = fields.Many2many("res.users", "prometeo_ai_routine_recipient_rel", "routine_id", "user_id",
                                     "Destinatarios")
    is_public = fields.Boolean("Pública", default=True, help="La ven todos los usuarios del agente.")
    group_ids = fields.Many2many("res.groups", "prometeo_ai_routine_group_rel", "routine_id", "group_id",
                                 "Visible para grupos")
    ai_model_id = fields.Many2one("prometeo.ai.model", "Modelo de IA", domain=[("active", "=", True)],
                                  help="Vacío = modelo por defecto de Ajustes.")
    failure_count = fields.Integer("Errores seguidos", readonly=True, copy=False)
    incomplete_count = fields.Integer("Incompletas seguidas", readonly=True, copy=False)
    template_id = fields.Many2one("prometeo.ai.routine.template", "Plantilla", readonly=True)
    alert_ids = fields.One2many("prometeo.ai.alert", "routine_id", "Alertas")
    run_ids = fields.One2many("prometeo.ai.run", "routine_id", "Corridas")
    open_alert_count = fields.Integer("Alertas abiertas", compute="_compute_open_alert_count")

    def _compute_open_alert_count(self):
        """Cantidad de alertas abiertas por rutina."""
        groups = self.env["prometeo.ai.alert"].sudo()._read_group(
            [("routine_id", "in", self.ids), ("state", "=", "new")], ["routine_id"], ["__count"])
        counts = {routine.id: count for routine, count in groups}
        for rec in self:
            rec.open_alert_count = counts.get(rec.id, 0)

    # ------------------------------------------------------------------ calendario

    def _tz(self):
        """Zona horaria del usuario que ejecuta la rutina."""
        return pytz.timezone(self.run_as_user_id.tz or DEFAULT_TZ)

    def _at_hour(self, local_date):
        """Fecha local + run_hour → datetime UTC naive."""
        hours = int(self.run_hour)
        minutes = int(round((self.run_hour - hours) * 60))
        local = self._tz().localize(datetime.combine(local_date, datetime.min.time())
                                    + timedelta(hours=hours, minutes=minutes))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _next_run_after(self, dt):
        """Próxima ejecución después de `dt` (UTC naive)."""
        self.ensure_one()
        number = max(1, self.interval_number)
        if self.interval_type == "minutes":
            return dt + timedelta(minutes=number)
        if self.interval_type == "hours":
            return dt + timedelta(hours=number)
        local_date = pytz.utc.localize(dt).astimezone(self._tz()).date()
        delta = relativedelta(weeks=number) if self.interval_type == "weeks" else relativedelta(days=number)
        return self._at_hour(local_date + delta)

    def _first_run(self):
        """Primera ejecución: ya para minutos/horas; la próxima run_hour para días/semanas."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.interval_type in ("minutes", "hours"):
            return now
        today = pytz.utc.localize(now).astimezone(self._tz()).date()
        candidate = self._at_hour(today)
        return candidate if candidate > now else self._at_hour(today + timedelta(days=1))

    @api.model_create_multi
    def create(self, vals_list):
        """Calcula la primera ejecución si no viene dada."""
        records = super().create(vals_list)
        for rec, vals in zip(records, vals_list):
            if not vals.get("next_run"):
                rec.next_run = rec._first_run()
        return records

    def write(self, vals):
        """Si cambia la frecuencia, recalcula la próxima ejecución."""
        res = super().write(vals)
        if FREQUENCY_FIELDS & set(vals) and "next_run" not in vals:
            for rec in self:
                rec.next_run = rec._first_run()
        return res

    # ------------------------------------------------------------------ ejecución

    def _resolve_model(self):
        """Modelo propio o por defecto; UserError si no hay ninguno utilizable."""
        model = self.sudo().ai_model_id.filtered("active") or self.env["prometeo.ai.model"]._get_default()
        if not model:
            raise UserError(_("No hay modelo de IA: elegí uno en la rutina o configurá el modelo por defecto."))
        return model

    def _user_env(self):
        """Entorno del usuario 'ejecutar como', restringido a las empresas de la rutina."""
        user = self.sudo().run_as_user_id
        if not user or not user.active:
            raise UserError(_("El usuario '%s' de 'Ejecutar como' no está activo.", user.name or "?"))
        companies = (self.sudo().company_ids & user.company_ids) or user.company_id
        return self.env(user=user, context=dict(self.env.context, allowed_company_ids=companies.ids))

    def _first_message(self):
        """Instrucción de la rutina + alertas abiertas o silenciadas, para no repetirlas."""
        now = fields.Datetime.now()
        alerts = self.env["prometeo.ai.alert"].sudo().search([
            ("routine_id", "=", self.id), "|", ("state", "=", "new"),
            "&", ("state", "=", "dismissed"), ("silenced_until", ">", now)])
        listing = [{"id": a.id, "key": a.dedup_key, "title": a.name,
                    "state": "abierta" if a.state == "new" else "silenciada"} for a in alerts]
        text = "%s\n\nAlertas de esta rutina que ya existen (no las dupliques; cerrá las abiertas que ya no apliquen):\n%s" % (
            self.prompt or "", json.dumps(listing, ensure_ascii=False))
        return {"role": "user", "content": text}

    def _run_once(self):
        """Ejecuta la rutina una vez y devuelve el registro de consumo."""
        self.ensure_one()
        routine = self.sudo()
        Run = self.env["prometeo.ai.run"]
        Alert = self.env["prometeo.ai.alert"]
        now = fields.Datetime.now()
        started = time.monotonic()
        vals = {"last_run": now, "next_run": routine._next_run_after(now)}
        if Run._cap_reached():
            run = Run._log("routine", routine.ai_model_id, {}, routine=routine, status="skipped_cap")
            Alert._create_system_alert(
                "tope-%s" % now.strftime("%Y-%m"), _("Se alcanzó el tope de gasto mensual"),
                _("Las rutinas y el chat quedan en pausa hasta el mes próximo o hasta subir el tope en Ajustes."),
                "high")
            routine.write(dict(vals, last_status="skipped_cap"))
            return run
        ai_model = None
        try:
            if not routine.recipient_ids:
                raise UserError(_("La rutina no tiene destinatarios."))
            ai_model = routine._resolve_model()
            env_u = routine._user_env()
            ctx = tools.new_context(routine=routine)
            with self.env.cr.savepoint():
                result = loop.run_agent(
                    env_u, ai_model, prompts.build_system_prompt(env_u, "routine"), [routine._first_message()],
                    tools.READ_TOOLS + tools.ALERT_TOOLS, ctx, get_param(self.env, "routine_max_tool_calls"),
                    get_param(self.env, "routine_max_seconds"), extra_tools=tools.alert_tool_handlers())
        except (llm.LlmError, UserError) as e:
            return routine._register_failure(vals, ai_model, str(e), time.monotonic() - started)
        except Exception as e:  # noqa: BLE001 - una rutina rota no debe tirar el despachador
            _logger.exception("Rutina %s falló", routine.id)
            return routine._register_failure(vals, ai_model, str(e) or e.__class__.__name__,
                                             time.monotonic() - started)
        status = result["status"]
        run = Run._log("routine", ai_model, result, routine=routine, status=status,
                       duration=time.monotonic() - started)
        vals.update(last_status=status, failure_count=0,
                    incomplete_count=routine.incomplete_count + 1 if status == "incomplete" else 0)
        routine.write(vals)
        if routine.incomplete_count == MAX_INCOMPLETE:
            Alert._create_system_alert(
                "incompleta-%s" % routine.id, _("La rutina '%s' no llega a terminar", routine.name),
                _("Tres corridas seguidas chocaron con el límite de tiempo o de consultas. "
                  "Simplificá la instrucción o subí los límites en Ajustes."))
        return run

    def _register_failure(self, vals, ai_model, message, duration):
        """Registra una corrida con error, suma la falla y pausa a la tercera."""
        run = self.env["prometeo.ai.run"]._log("routine", ai_model, {}, routine=self, status="error",
                                               error=message, duration=duration)
        failures = self.failure_count + 1
        vals.update(last_status="error", failure_count=failures)
        if failures >= MAX_FAILURES:
            vals["paused"] = True
        self.write(vals)
        if failures >= MAX_FAILURES:
            self.env["prometeo.ai.alert"]._create_system_alert(
                "pausada-%s" % self.id, _("La rutina '%s' se pausó", self.name),
                _("Falló %(n)s veces seguidas. Último error: %(error)s", n=failures, error=message), "high")
        return run

    def action_run_now(self):
        """Ejecuta la rutina ya, sin esperar al cron."""
        self.ensure_one()
        run = self._run_once()
        labels = dict(run._fields["status"].selection)
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "danger" if run.status == "error" else "success",
            "message": _("Corrida %(status)s. %(error)s", status=labels[run.status].lower(), error=run.error or ""),
            "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_resume(self):
        """Reanuda una rutina pausada por errores."""
        self.sudo().write({"paused": False, "failure_count": 0})
        return True

    def action_view_alerts(self):
        """Alertas de la rutina."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("prometeo_ai_agent.action_alert_inbox")
        action["domain"] = [("routine_id", "=", self.id)]
        return action

    @api.model
    def _cron_dispatch(self):
        """Corre las rutinas vencidas, con presupuesto de tiempo por pasada."""
        started = time.monotonic()
        due = self.sudo().search([("active", "=", True), ("paused", "=", False),
                                  ("next_run", "<=", fields.Datetime.now())], order="next_run")
        for routine in due:
            if time.monotonic() - started > DISPATCH_BUDGET_SECONDS:
                self.env.ref("prometeo_ai_agent.cron_dispatch")._trigger()
                break
            try:
                routine._run_once()
            except Exception:  # noqa: BLE001
                _logger.exception("Despachador: la rutina %s falló", routine.id)
            if not tools_config["test_enable"]:
                self.env.cr.commit()
