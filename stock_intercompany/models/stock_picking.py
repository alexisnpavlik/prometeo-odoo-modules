# Copyright 2021 Camptocamp
# Copyright 2026 Alexis Medina
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import Command, api, fields, models

from .intercompany_sync import get_counterpart


class StockPicking(models.Model):
    _inherit = "stock.picking"

    counterpart_of_picking_id = fields.Many2one("stock.picking", check_company=False)
    counterpart_picking_id = fields.Many2one(
        "stock.picking",
        string="Contraparte intercompany",
        compute="_compute_counterpart_picking_id",
        check_company=False,
    )

    @api.depends("counterpart_of_picking_id")
    def _compute_counterpart_picking_id(self):
        """Resuelve el espejo en los dos sentidos: hacia el origen y hacia la copia."""
        for picking in self:
            picking.counterpart_picking_id = get_counterpart(
                picking, "counterpart_of_picking_id"
            )

    def _create_counterpart_picking(self):
        companies = self.env["res.company"].sudo().search([])
        partners = {cp.partner_id: cp for cp in companies}
        picking = self.env["stock.picking"]
        if self.partner_id in partners:
            company = partners[self.partner_id]
            # Switch to target company context before creating picking
            picking_model = self.env["stock.picking"].sudo().with_company(company)
            vals = self._get_counterpart_picking_vals(company)
            # Create picking in correct company context
            picking = picking_model.create(vals)
            # El compute de counterpart_picking_id depende de
            # counterpart_of_picking_id, campo que solo llena el espejo
            # apuntando a self: depends() no puede rastrear la búsqueda
            # inversa que hace get_counterpart(). Si algo leyó
            # self.counterpart_picking_id antes de este create (p. ej. un
            # guard en action_confirm/button_validate), quedó cacheado
            # vacío y no se refresca solo. Se invalida a mano apenas existe
            # el espejo para que cualquier lectura posterior de self lo
            # recalcule.
            self.invalidate_recordset(["counterpart_picking_id"])
            # "picking_id" en stock.move.line es un campo propio (no
            # derivado de move_id), así que no se completa solo al crear
            # las líneas anidadas dentro de move_ids: hay que sincronizarlo
            # a mano para que picking.move_line_ids las vea.
            picking.move_ids.move_line_ids.picking_id = picking.id
            # Confirm picking in the same company context. merge=False:
            # el merge automático de moves de Odoo colapsaría dos moves
            # espejo del mismo producto en uno solo, perdiendo la relación
            # 1 a 1 con counterpart_of_move_id que este módulo necesita.
            picking.move_ids.filtered(
                lambda m: m.state == "draft"
            )._action_confirm(merge=False)
        return picking

    def _get_counterpart_picking_vals(self, company):
        # Get warehouse and picking type in correct company context
        warehouse = False
        with_company = self.env["stock.warehouse"].sudo().with_company(company)
        ptype = False

        if company.intercompany_in_type_id:
            ptype = company.intercompany_in_type_id
            if ptype.warehouse_id:
                warehouse = ptype.warehouse_id

        if not warehouse:
            warehouse = with_company.search([("company_id", "=", company.id)], limit=1)

        if not ptype:
            ptype = warehouse.in_type_id

        # Ensure locations belong to correct company
        location_dest = ptype.default_location_dest_id or warehouse.lot_stock_id
        supplier_location = self.env.ref("stock.stock_location_suppliers")

        move_ids = self._get_counterpart_move_commands(company, ptype)

        return {
            "partner_id": self.company_id.partner_id.id,
            "company_id": company.id,
            "origin": self.name,
            "picking_type_id": ptype.id,
            "state": "draft",
            "location_id": supplier_location.id,
            "location_dest_id": location_dest.id,
            "counterpart_of_picking_id": self.id,
            "move_ids": move_ids,
            "scheduled_date": self.scheduled_date,
            "priority": self.priority,
        }

    def _get_counterpart_move_commands(self, company, picking_type):
        """Construye los moves espejo con sus líneas anidadas dentro de cada move.

        Ojo si reutilizás esto para crear líneas nueva: las líneas quedan
        con ``picking_id=False`` a propósito, porque el ORM solo completa
        el inverso del o2m que se está anidando (``move_id``, vía
        ``move_line_ids`` del move) y ``picking_id`` en
        ``stock.move.line`` es un campo propio, no derivado de
        ``move_id``. Quien use estos commands para crear registros tiene
        que sincronizar ``picking_id`` a mano después (como hace
        ``_create_counterpart_picking`` con
        ``picking.move_ids.move_line_ids.picking_id = picking.id``), o
        las líneas quedan invisibles en ``picking.move_line_ids``.
        """
        supplier_location = self.env.ref("stock.stock_location_suppliers")
        if supplier_location.company_id:
            supplier_location.sudo().company_id = False

        location_dest = picking_type.default_location_dest_id
        if not location_dest:
            warehouse = (
                self.env["stock.warehouse"]
                .sudo()
                .search([("company_id", "=", company.id)], limit=1)
            )
            location_dest = warehouse.lot_stock_id

        common_vals = {
            "company_id": company.id,
            "location_id": supplier_location.id,
            "location_dest_id": location_dest.id,
            "picking_type_id": picking_type.id,
        }

        move_commands = []
        for move in self.move_ids.sudo():
            line_commands = []
            for line in move.move_line_ids:
                line_vals = line.with_company(company).copy_data(
                    dict(
                        common_vals,
                        move_id=False,
                        picking_id=False,
                        counterpart_of_line_id=line.id,
                    )
                )[0]
                line_commands.append(Command.create(line_vals))
            move_vals = move.with_company(company).copy_data(
                dict(
                    common_vals,
                    counterpart_of_move_id=move.id,
                    move_line_ids=line_commands,
                )
            )[0]
            move_commands.append(Command.create(move_vals))
        return move_commands

    def _action_done(self):
        counterparts = []
        for picking in self:
            if picking.location_dest_id.usage in ("customer", "transit"):
                counterpart = picking._create_counterpart_picking()
                counterparts.append((picking, counterpart))
        res = super()._action_done()
        for picking, counterpart in counterparts:
            picking._finalize_counterpart_picking(counterpart)
        return res

    def _finalize_counterpart_picking(self, counterpart_picking):
        """hook to finalize required steps on the counterpart picking after the initial
        outgoing picking is done"""
