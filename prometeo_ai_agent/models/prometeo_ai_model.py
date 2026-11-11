from odoo import api, fields, models


class PrometeoAiModel(models.Model):
    _name = "prometeo.ai.model"
    _description = "Modelo de IA"
    _order = "provider_id, label, name"

    provider_id = fields.Many2one("prometeo.ai.provider", "Proveedor", required=True, ondelete="cascade")
    provider_type = fields.Selection(related="provider_id.provider_type", store=True)
    name = fields.Char("Identificador técnico", required=True)
    label = fields.Char("Nombre")
    active = fields.Boolean("Activo", default=False)
    price_input = fields.Float("USD por millón de tokens de entrada", digits=(12, 4))
    price_output = fields.Float("USD por millón de tokens de salida", digits=(12, 4))
    price_known = fields.Boolean("Precio cargado")

    _sql_constraints = [
        ("provider_name_uniq", "unique(provider_id, name)", "El modelo ya existe para este proveedor."),
    ]

    @api.depends("label", "name", "provider_id.name")
    def _compute_display_name(self):
        """Muestra '<nombre> (<proveedor>)'."""
        for rec in self:
            rec.display_name = "%s (%s)" % (rec.label or rec.name, rec.provider_id.name or "")

    @api.onchange("price_input", "price_output")
    def _onchange_price(self):
        """Editar un precio a mano lo marca como cargado."""
        for rec in self:
            if rec.price_input or rec.price_output:
                rec.price_known = True

    @api.model
    def _get_default(self):
        """Modelo por defecto configurado en Ajustes (vacío si no hay o está inactivo)."""
        value = self.env["ir.config_parameter"].sudo().get_param("prometeo_ai_agent.default_model_id")
        if not value or not str(value).isdigit():
            return self.browse()
        return self.sudo().browse(int(value)).exists().filtered("active")
