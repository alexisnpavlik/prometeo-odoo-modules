# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # Sin store=True a propósito: un campo calculado almacenado sobre stock.picking
    # obligaría a recalcular todos los albaranes históricos en cada actualización del
    # módulo. Solo se usa para mostrar u ocultar el botón en el formulario; el listado
    # de entregas filtra por ubicación, que ya está indexada.
    cvi_is_vendor_move = fields.Boolean(
        string="Es movimiento de mercadería de vendedor",
        compute="_compute_cvi_is_vendor_move",
    )
    cvi_reversal_id = fields.Many2one(
        "stock.picking",
        string="Anulado por",
        readonly=True,
        copy=False,
        help="Albarán inverso que anuló esta entrega.",
    )
    cvi_reversed_id = fields.Many2one(
        "stock.picking",
        string="Anula a",
        readonly=True,
        copy=False,
        help="Entrega que este albarán anula.",
    )

    @api.depends("location_id.cvi_is_vendor_location", "location_dest_id.cvi_is_vendor_location")
    def _compute_cvi_is_vendor_move(self):
        """Marca los albaranes que mueven mercadería hacia o desde un vendedor."""
        for picking in self:
            picking.cvi_is_vendor_move = (
                picking.location_id.cvi_is_vendor_location
                or picking.location_dest_id.cvi_is_vendor_location
            )

    def action_cvi_reverse_delivery(self):
        """Anula una entrega generando y validando el albarán inverso (HU-02, HU-04).

        Un albarán validado no se borra ni se edita: los movimientos de stock son
        inmutables una vez hechos, y de eso depende poder reconstruir el stock de
        cualquier fecha pasada. Anular acá significa revertir: se genera el movimiento
        opuesto y quedan las dos operaciones registradas y enlazadas.
        """
        self.ensure_one()
        if not self.cvi_is_vendor_move:
            raise UserError(_(
                "%s no es una entrega de mercadería a un vendedor.", self.name
            ))
        if self.state != "done":
            raise UserError(_(
                "Solo se anula una entrega ya validada. %(picking)s está en estado "
                "%(state)s: cancelala con el botón estándar de Odoo.",
                picking=self.name,
                state=self.state,
            ))
        if self.cvi_reversal_id:
            raise UserError(_(
                "%(picking)s ya fue anulada por %(reversal)s.",
                picking=self.name,
                reversal=self.cvi_reversal_id.name,
            ))
        if self.cvi_reversed_id:
            raise UserError(_(
                "%(picking)s es la anulación de %(original)s. Anular una anulación "
                "volvería a entregar la mercadería: cargá una entrega nueva.",
                picking=self.name,
                original=self.cvi_reversed_id.name,
            ))

        self._cvi_check_reversible()
        reversal = self.create({
            "picking_type_id": self.picking_type_id.id,
            "location_id": self.location_dest_id.id,
            "location_dest_id": self.location_id.id,
            "partner_id": self.partner_id.id,
            "origin": _("Anulación de %s", self.name),
            "cvi_reversed_id": self.id,
            "move_ids": [(0, 0, {
                "name": move.product_id.display_name,
                "product_id": move.product_id.id,
                "product_uom_qty": move.quantity,
                "product_uom": move.product_uom.id,
                "location_id": self.location_dest_id.id,
                "location_dest_id": self.location_id.id,
            }) for move in self.move_ids if move.quantity > 0],
        })
        reversal.action_confirm()
        reversal.action_assign()
        for move in reversal.move_ids:
            move.quantity = move.product_uom_qty
        reversal.button_validate()
        if reversal.state != "done":
            raise UserError(_(
                "No se pudo validar la anulación de %(picking)s: quedó en estado "
                "%(state)s.",
                picking=self.name,
                state=reversal.state,
            ))
        self.cvi_reversal_id = reversal
        _logger.info("Entrega %s anulada por %s", self.name, reversal.name)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Entrega anulada"),
                "message": _(
                    "%(original)s quedó anulada por %(reversal)s. La mercadería volvió "
                    "a su origen.",
                    original=self.name,
                    reversal=reversal.name,
                ),
                # Ver la nota en cvi_vendor_delivery_wizard: clean_action() no completa
                # "views" en una act_window anidada dentro de un ir.actions.client.
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": "stock.picking",
                    "res_id": reversal.id,
                    "view_mode": "form",
                    "views": [[False, "form"]],
                    "target": "current",
                },
            },
        }

    def _cvi_check_reversible(self):
        """Verifica que la mercadería siga en destino antes de intentar revertirla.

        Este chequeo es la única barrera: sin él Odoo no se queja, valida el albarán
        inverso igual y deja la ubicación del vendedor en negativo. Es decir, anular una
        entrega cuyos muebles ya se vendieron inventaría stock que no existe. Verificado
        desactivando el chequeo: la anulación se completa sin ningún error.
        """
        self.ensure_one()
        quant = self.env["stock.quant"]
        faltantes = []
        for move in self.move_ids:
            if move.quantity <= 0:
                continue
            disponible = quant._get_available_quantity(
                move.product_id, self.location_dest_id
            )
            if disponible < move.quantity:
                faltantes.append(_(
                    "%(product)s: se entregaron %(sent)s y quedan %(left)s",
                    product=move.product_id.display_name,
                    sent=move.quantity,
                    left=disponible,
                ))
        if faltantes:
            raise UserError(_(
                "No se puede anular %(picking)s: la mercadería ya no está disponible "
                "en destino, probablemente porque se vendió.\n\n%(detail)s\n\n"
                "Si hubo una venta, corregila desde la tarjeta en vez de anular la "
                "entrega.",
                picking=self.name,
                detail="\n".join(faltantes),
            ))
