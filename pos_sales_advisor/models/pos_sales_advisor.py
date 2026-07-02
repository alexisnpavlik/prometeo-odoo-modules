import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosSalesAdvisor(models.Model):
    _name = "pos.sales.advisor"
    _inherit = ["pos.load.mixin"]
    _description = "Asesor de Venta POS"
    _order = "name"

    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        default=lambda self: self.env.company,
        help="Dejar vacío para que el asesor esté disponible en todas las compañías.",
    )

    @api.model
    def _load_pos_data_domain(self, data):
        """Dominio de carga al POS: asesores de la compañía de la caja o compartidos.

        Los archivados quedan excluidos automáticamente por el campo active.
        """
        config = self.env["pos.config"].browse(data["pos.config"]["data"][0]["id"])
        return [
            "|",
            ("company_id", "=", False),
            ("company_id", "=", config.company_id.id),
        ]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Campos del asesor expuestos al frontend del POS."""
        return ["id", "name"]
