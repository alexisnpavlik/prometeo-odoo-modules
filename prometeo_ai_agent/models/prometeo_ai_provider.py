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
    check_state = fields.Selection([("ok", "Conectado"), ("error", "Error")], "Conexión", readonly=True, copy=False)
    check_message = fields.Char("Resultado de la prueba", readonly=True, copy=False)
    check_date = fields.Datetime("Probado el", readonly=True, copy=False)
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

    def _sync_models(self, listed):
        """Crea los modelos que falten. Si el proveedor no tiene ninguno activo, activa los de precio conocido."""
        self.ensure_one()
        Model = self.env["prometeo.ai.model"].sudo().with_context(active_test=False)
        existing = set(Model.search([("provider_id", "=", self.id)]).mapped("name"))
        vals_list = []
        for item in listed:
            if item["name"] in existing:
                continue
            existing.add(item["name"])
            price = llm.prices.lookup_price(self.provider_type, item["name"])
            vals_list.append({
                "provider_id": self.id, "name": item["name"], "label": item.get("label") or item["name"],
                "active": False, "price_input": price[0] if price else 0.0,
                "price_output": price[1] if price else 0.0, "price_known": bool(price)})
        created = Model.create(vals_list)
        mine = Model.search([("provider_id", "=", self.id)])
        if not mine.filtered("active"):
            mine.filtered("price_known").write({"active": True})
        self._ensure_default_model()
        return created

    def _ensure_default_model(self):
        """Si no hay modelo por defecto, elige uno activo con precio: el más barato que no sea 'lite'."""
        if self.env["prometeo.ai.model"]._get_default():
            return
        active = self.env["prometeo.ai.model"].sudo().search([("active", "=", True), ("price_known", "=", True)],
                                                             order="price_input, id")
        choice = active.filtered(lambda m: "lite" not in m.name)[:1] or active[:1]
        if choice:
            self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.default_model_id", choice.id)

    def _check_connection(self):
        """Prueba la clave listando los modelos y deja el resultado en check_state/check_message."""
        for provider in self.sudo():
            now = fields.Datetime.now()
            if not provider.api_key:
                provider.write({"check_state": False, "check_message": False, "check_date": False})
                continue
            try:
                listed = llm.list_models(provider._get_credentials())
            except llm.LlmError as e:
                provider.write({"check_state": "error", "check_date": now,
                                "check_message": str(e).split(" Detalle:")[0][:300]})
                continue
            provider._sync_models(listed)
            active = provider.with_context(active_test=False).model_ids.filtered("active")
            provider.write({"check_state": "ok", "check_date": now, "check_message": _(
                "Clave válida: %(total)s modelos disponibles, %(active)s activos.",
                total=len(listed), active=len(active))})

    def write(self, vals):
        """Al cambiar la clave o la URL, la prueba en el momento."""
        res = super().write(vals)
        if ("api_key" in vals or "base_url" in vals) and not self.env.context.get("skip_ai_check"):
            self.with_context(skip_ai_check=True)._check_connection()
        return res

    def action_fetch_models(self):
        """Prueba la clave, trae los modelos y avisa el resultado."""
        self.ensure_one()
        self._get_credentials()
        before = len(self.with_context(active_test=False).model_ids)
        self.with_context(skip_ai_check=True)._check_connection()
        if self.check_state != "ok":
            raise UserError(_("No se pudo conectar: %s", self.check_message))
        new = len(self.with_context(active_test=False).model_ids) - before
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "message": _("%(msg)s %(new)s nuevos.", msg=self.check_message, new=new),
            "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}
