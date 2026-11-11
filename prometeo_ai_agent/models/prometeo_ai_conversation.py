import logging
import time

from odoo import _, api, fields, models
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
            return {"status": "error", "message": _("Configurá un modelo por defecto en Ajustes > Agente IA.")}
        user_message = {"role": "user", "content": text}
        started = time.monotonic()
        try:
            with self.env.cr.savepoint():
                result = loop.run_agent(
                    self.env, ai_model, prompts.build_system_prompt(self.env, "chat"),
                    self._history() + [user_message], tools.READ_TOOLS, tools.new_context(),
                    get_param(self.env, "chat_max_tool_calls"), get_param(self.env, "chat_max_seconds"))
                self._store([user_message] + result["new_messages"])
                if not self.name:
                    self.name = text[:NAME_LENGTH]
                if model_id and ai_model != self.ai_model_id:
                    self.ai_model_id = ai_model
        except (llm.LlmError, UserError) as e:
            _logger.info("Chat %s: error del proveedor: %s", self.id, e)
            Run._log("chat", ai_model, {}, user=self.env.user, status="error", error=str(e),
                     duration=time.monotonic() - started)
            return {"status": "error", "message": _("El proveedor de IA no respondió. Probá de nuevo.")}
        Run._log("chat", ai_model, result, user=self.env.user, status=result["status"],
                 duration=time.monotonic() - started)
        return {"status": "ok", "reply": result["text"]}

    def _store(self, messages):
        """Guarda mensajes normalizados."""
        self.env["prometeo.ai.message"].create([{
            "conversation_id": self.id, "role": m["role"], "content": m.get("content") or "",
            "tool_calls": m.get("tool_calls") or False, "tool_call_id": m.get("tool_call_id"),
            "tool_name": m.get("name"), "raw": m.get("raw") or False, "raw_provider": m.get("raw_provider"),
        } for m in messages])
