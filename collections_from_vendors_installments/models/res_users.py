# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    cvi_stock_location_id = fields.Many2one(
        "stock.location",
        string="Ubicación de mercadería",
        readonly=True,
        copy=False,
        help="Ubicación interna donde vive la mercadería que este vendedor tiene en la calle. "
             "Se crea sola la primera vez que se le entrega mercadería.",
    )

    cvi_supervised_collector_ids = fields.Many2many(
        "res.users",
        "cvi_supervised_rel", "supervisor_id", "collector_id",
        string="Cobradores supervisados",
        compute="_compute_cvi_supervised_collectors",
        help="Cobradores con asignación vigente hoy. Lo usan las reglas de registro "
             "del supervisor, que no pueden llamar a un método (HU-21).",
    )

    def _compute_cvi_supervised_collectors(self):
        """Cobradores que este usuario supervisa hoy.

        Se calcula en vez de guardarse porque depende de la fecha de hoy, que no es un
        campo: una asignación vencida tiene que dejar de contar sola.
        """
        assignment = self.env["cvi.supervision.assignment"].sudo()
        current = assignment._cvi_current_domain()
        for user in self:
            assignments = assignment.search(
                [("supervisor_id", "=", user.id)] + current
            )
            user.cvi_supervised_collector_ids = assignments.mapped("collector_id")

    def _cvi_get_location(self):
        """Devuelve la ubicación de stock del vendedor, creándola si todavía no existe.

        Se crea on-demand para no obligar a configurar una ubicación por usuario antes
        de empezar a operar.
        """
        self.ensure_one()
        # Bloqueo de la fila del usuario: sin esto, dos entregas simultáneas al mismo
        # vendedor crean dos ubicaciones y una queda huérfana pero marcada, ensuciando
        # el reporte de mercadería en la calle.
        self.env.cr.execute(
            "SELECT cvi_stock_location_id FROM res_users WHERE id = %s FOR UPDATE",
            (self.id,),
        )
        self.invalidate_recordset(["cvi_stock_location_id"])
        if self.cvi_stock_location_id:
            return self.cvi_stock_location_id
        parent = self.env.ref("collections_from_vendors_installments.stock_location_vendors")
        location = self.env["stock.location"].sudo().create({
            "name": self.name,
            "usage": "internal",
            "location_id": parent.id,
            "company_id": self.company_id.id,
            "cvi_is_vendor_location": True,
        })
        self.sudo().cvi_stock_location_id = location
        return location
