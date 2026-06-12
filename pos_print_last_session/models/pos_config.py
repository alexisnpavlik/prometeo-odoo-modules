# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class PosConfig(models.Model):
    _inherit = "pos.config"

    def action_print_last_closed_session(self):
        """Imprime el reporte de detalles de venta de la última sesión cerrada de esta caja."""
        self.ensure_one()
        session = self.env["pos.session"].search(
            [("config_id", "=", self.id), ("state", "=", "closed")],
            order="stop_at desc",
            limit=1,
        )
        if not session:
            raise UserError(_("La caja %s no tiene sesiones cerradas.", self.name))
        return self.env.ref("point_of_sale.sale_details_report").report_action(session)
