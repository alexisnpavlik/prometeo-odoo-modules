from odoo import fields, models


class PrometeoAiRoutine(models.Model):
    _name = "prometeo.ai.routine"
    _description = "Rutina del agente IA"

    name = fields.Char("Nombre", required=True)
    recipient_ids = fields.Many2many("res.users", "prometeo_ai_routine_recipient_rel", "routine_id", "user_id",
                                     "Destinatarios")
