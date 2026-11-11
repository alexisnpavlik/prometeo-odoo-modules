from odoo import fields, models


class PrometeoAiMessage(models.Model):
    _name = "prometeo.ai.message"
    _description = "Mensaje de una conversación con el agente IA"
    _order = "id"

    conversation_id = fields.Many2one("prometeo.ai.conversation", required=True, ondelete="cascade", index=True)
    role = fields.Selection([("user", "Usuario"), ("assistant", "Agente"), ("tool", "Herramienta")], required=True)
    content = fields.Text()
    tool_calls = fields.Json()
    tool_call_id = fields.Char()
    tool_name = fields.Char()
    raw = fields.Json()
    raw_provider = fields.Char()

    def _to_normalized(self):
        """Mensaje en el formato de la capa llm."""
        self.ensure_one()
        if self.role == "user":
            return {"role": "user", "content": self.content or ""}
        if self.role == "assistant":
            return {"role": "assistant", "content": self.content or "", "tool_calls": self.tool_calls or [],
                    "raw": self.raw or None, "raw_provider": self.raw_provider}
        return {"role": "tool", "tool_call_id": self.tool_call_id, "name": self.tool_name,
                "content": self.content or ""}
