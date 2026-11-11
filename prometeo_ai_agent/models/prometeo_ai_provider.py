from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .. import llm

PROVIDER_TYPES = [("anthropic", "Claude (Anthropic)"), ("openai", "OpenAI / compatible"), ("google", "Google Gemini")]


class PrometeoAiProvider(models.Model):
    _name = "prometeo.ai.provider"
    _description = "Proveedor de IA"
    _order = "name"

    name = fields.Char("Nombre", required=True)
    provider_type = fields.Selection(PROVIDER_TYPES, "Tipo", required=True, default="anthropic")
    api_key = fields.Char("Clave de API", groups="prometeo_ai_agent.group_admin", copy=False)
    base_url = fields.Char("URL base", required=True, default=lambda self: llm.DEFAULT_BASE_URLS["anthropic"])
    active = fields.Boolean(default=True)
    model_ids = fields.One2many("prometeo.ai.model", "provider_id", "Modelos",
                                context={"active_test": False})

    @api.onchange("provider_type")
    def _onchange_provider_type(self):
        """Completa la URL oficial del tipo elegido."""
        for rec in self:
            rec.base_url = llm.DEFAULT_BASE_URLS.get(rec.provider_type, rec.base_url)

    def _get_credentials(self):
        """Devuelve el proveedor en el formato que usa la capa llm (lee la clave con sudo)."""
        self.ensure_one()
        rec = self.sudo()
        if not rec.api_key:
            raise UserError(_("El proveedor %s no tiene clave de API cargada.", rec.name))
        return {"type": rec.provider_type, "api_key": rec.api_key, "base_url": rec.base_url.rstrip("/")}
