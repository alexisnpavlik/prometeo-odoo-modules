from odoo import _, api, fields, models

from .prometeo_ai_routine import INTERVALS


class PrometeoAiRoutineTemplate(models.Model):
    _name = "prometeo.ai.routine.template"
    _description = "Plantilla de rutina del agente IA"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)
    name = fields.Char("Nombre", required=True)
    description = fields.Text("Descripción")
    prompt = fields.Text("Instrucción", required=True)
    required_module = fields.Char("Módulo requerido", help="Nombre técnico del módulo de Odoo que necesita.")
    interval_number = fields.Integer("Cada", default=1)
    interval_type = fields.Selection(INTERVALS, "Unidad", default="days")
    run_hour = fields.Float("Hora", default=8.0)
    is_available = fields.Boolean("Disponible", compute="_compute_is_available", search="_search_is_available")

    def _installed_modules(self):
        """Nombres de los módulos instalados."""
        return set(self.env["ir.module.module"].sudo().search([("state", "=", "installed")]).mapped("name"))

    @api.depends("required_module")
    def _compute_is_available(self):
        """Disponible si el módulo requerido está instalado (o no requiere ninguno)."""
        installed = self._installed_modules()
        for rec in self:
            rec.is_available = not rec.required_module or rec.required_module in installed

    def _search_is_available(self, operator, value):
        """Búsqueda por disponibilidad."""
        installed = self._installed_modules()
        ids = self.search([]).filtered(
            lambda t: not t.required_module or t.required_module in installed).ids
        positive = (operator in ("=", "==") and value) or (operator == "!=" and not value)
        return [("id", "in" if positive else "not in", ids)]

    def action_run_in_chat(self):
        """Corre la instrucción ahora en el chat, con los permisos de quien la ejecuta. No crea rutina."""
        self.ensure_one()
        return {"type": "ir.actions.client", "tag": "prometeo_ai_agent.chat", "name": _("Chat"),
                "params": {"prompt": self.prompt, "title": self.name}}

    def action_use(self):
        """Crea una rutina activa a partir de la plantilla y abre su formulario."""
        self.ensure_one()
        routine = self.env["prometeo.ai.routine"].create({
            "name": self.name, "prompt": self.prompt, "template_id": self.id,
            "interval_number": self.interval_number, "interval_type": self.interval_type,
            "run_hour": self.run_hour, "run_as_user_id": self.env.uid,
            "recipient_ids": [(6, 0, [self.env.uid])], "company_ids": [(6, 0, self.env.user.company_ids.ids)]})
        return {"type": "ir.actions.act_window", "name": _("Rutina"), "res_model": "prometeo.ai.routine",
                "res_id": routine.id, "view_mode": "form", "views": [(False, "form")], "target": "current"}
