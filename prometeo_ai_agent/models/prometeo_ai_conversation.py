import logging
import time

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.tools import config as tools_config
from odoo.exceptions import UserError

from .. import llm
from ..agent import loop, prompts, tools
from .params import get_param

_logger = logging.getLogger(__name__)

CHAT_LOCK_KEY = 7262001
HISTORY_LIMIT = 40
NAME_LENGTH = 60


class PrometeoAiConversation(models.Model):
    _name = "prometeo.ai.conversation"
    _description = "Conversación con el agente IA"
    _order = "write_date desc, id desc"

    name = fields.Char("Título")
    user_id = fields.Many2one("res.users", "Usuario", required=True, default=lambda self: self.env.user,
                              index=True, ondelete="cascade")
    ai_model_id = fields.Many2one("prometeo.ai.model", "Modelo de IA")
    message_ids = fields.One2many("prometeo.ai.message", "conversation_id", "Mensajes")

    @api.model
    def get_available_models(self):
        """Modelos activos para el selector del chat."""
        default = self.env["prometeo.ai.model"]._get_default()
        models_ = self.env["prometeo.ai.model"].sudo().search([("active", "=", True)])
        return [{"id": m.id, "label": m.display_name, "is_default": m == default} for m in models_]

    @api.model
    def get_activation_message(self):
        """Mensaje cuando el asistente no está activado: invita a contactar a soporte."""
        contact = get_param(self.env, "support_contact")
        who = _("a soporte (%s)", contact) if contact else _("a soporte")
        return _("El Asistente IA todavía no está activado en tu cuenta. Contactá %s para sumarlo: "
                 "vas a poder preguntarle a tus datos en lenguaje natural y recibir alertas automáticas "
                 "sobre stock, ventas, caja y más.", who)

    def get_messages(self):
        """Mensajes visibles (usuario y respuestas con texto)."""
        self.ensure_one()
        return [{"id": m.id, "role": m.role, "content": m.content, "date": fields.Datetime.to_string(m.create_date)}
                for m in self.message_ids
                if m.role == "user" or (m.role == "assistant" and m.content)]

    def _history(self):
        """Últimos mensajes en formato normalizado, empezando por un mensaje del usuario."""
        messages = self.message_ids[-HISTORY_LIMIT:]
        while messages and messages[0].role != "user":
            messages = messages[1:]
        return [m._to_normalized() for m in messages]

    def _take_slot(self):
        """Toma un lugar de chat con un candado de transacción. False si están todos ocupados."""
        for slot in range(max(1, get_param(self.env, "chat_max_concurrent"))):
            self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (CHAT_LOCK_KEY, slot))
            if self.env.cr.fetchone()[0]:
                return True
        return False

    def _resolve_model(self, model_id):
        """Modelo pedido, el de la conversación o el por defecto."""
        Model = self.env["prometeo.ai.model"].sudo()
        if model_id:
            model = Model.browse(int(model_id)).exists().filtered("active")
            if model:
                return model
        return self.sudo().ai_model_id.filtered("active") or Model._get_default()

    def send_message(self, text, model_id=None):
        """Turno de chat síncrono. Devuelve {'status': ok|busy|cap|error, ...}."""
        self.ensure_one()
        self.check_access("write")
        text = (text or "").strip()
        if not text:
            raise UserError(_("Escribí un mensaje."))
        Run = self.env["prometeo.ai.run"]
        if Run._cap_reached():
            return {"status": "cap"}
        if not self._take_slot():
            return {"status": "busy"}
        ai_model = self._resolve_model(model_id)
        if not ai_model:
            return {"status": "error", "message": self.get_activation_message()}
        user_message = {"role": "user", "content": text}
        started = time.monotonic()
        try:
            # Todas las empresas a las que el usuario tiene acceso, no solo las elegidas en el selector.
            env_all = self.env(context=dict(self.env.context, allowed_company_ids=self.env.user.company_ids.ids))
            with self.env.cr.savepoint():
                result = loop.run_agent(
                    env_all, ai_model, prompts.build_system_prompt(env_all, "chat"),
                    self._history() + [user_message], tools.READ_TOOLS, tools.new_context(),
                    get_param(self.env, "chat_max_tool_calls"), get_param(self.env, "chat_max_seconds"),
                    on_step=self._publish_step, max_input_tokens=get_param(self.env, "chat_max_input_tokens"))
                self._store([user_message] + result["new_messages"])
                if not self.name:
                    self.name = text[:NAME_LENGTH]
                if model_id and ai_model != self.ai_model_id:
                    self.ai_model_id = ai_model
        except (llm.LlmError, UserError) as e:
            _logger.info("Chat %s: error del proveedor: %s", self.id, e)
            Run._log("chat", ai_model, getattr(e, "usage", None) or {}, user=self.env.user, status="error", error=str(e),
                     duration=time.monotonic() - started)
            return {"status": "error", "message": self._friendly_error(e)}
        except Exception as e:  # noqa: BLE001
            _logger.exception("Chat %s: error inesperado", self.id)
            Run._log("chat", ai_model, getattr(e, "usage", None) or {}, user=self.env.user, status="error",
                     error=str(e), duration=time.monotonic() - started)
            return {"status": "error", "message": _("Ocurrió un error inesperado. Probá de nuevo.")}
        Run._log("chat", ai_model, result, user=self.env.user, status=result["status"],
                 duration=time.monotonic() - started)
        return {"status": "ok", "reply": result["text"]}

    def _friendly_error(self, error):
        """Mensaje para el usuario: qué pasó en simple y a quién avisar. El detalle técnico, solo al admin."""
        status = getattr(error, "status", None)
        contact = get_param(self.env, "support_contact")
        support = (_("Contactá a soporte: %s.", contact) if contact
                   else _("Avisale al administrador del sistema."))
        if status == 402:
            text = _("Se acabaron los créditos del servicio de IA. %s", support)
        elif status in (401, 403):
            text = _("La clave del servicio de IA no es válida o venció. %s", support)
        elif status == 429:
            text = _("El servicio de IA está saturado. Probá de nuevo en unos minutos.")
        elif isinstance(error, UserError):
            text = _("%(error)s %(support)s", error=str(error), support=support)
        else:
            text = _("El servicio de IA no respondió. Probá de nuevo; si sigue fallando: %s", support)
        if self.env.user.has_group("prometeo_ai_agent.group_admin") and not isinstance(error, UserError):
            text += "\n\n" + _("Detalle técnico: %s", str(error)[:300])
        return text

    def _publish_step(self, text):
        """Manda un paso al navegador por el bus, con un cursor propio para que llegue antes de terminar."""
        payload = {"conversation_id": self.id, "text": text}
        partner = self.env.user.partner_id
        if tools_config["test_enable"]:
            self.env["bus.bus"]._sendone(partner, "prometeo_ai_agent/step", payload)
            return
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env["bus.bus"]._sendone(env["res.partner"].browse(partner.id), "prometeo_ai_agent/step", payload)

    def _store(self, messages):
        """Guarda mensajes normalizados."""
        self.env["prometeo.ai.message"].create([{
            "conversation_id": self.id, "role": m["role"], "content": m.get("content") or "",
            "tool_calls": m.get("tool_calls") or False, "tool_call_id": m.get("tool_call_id"),
            "tool_name": m.get("name"), "raw": m.get("raw") or False, "raw_provider": m.get("raw_provider"),
        } for m in messages])
