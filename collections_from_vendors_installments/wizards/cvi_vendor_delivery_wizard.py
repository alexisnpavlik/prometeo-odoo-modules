# -*- coding: utf-8 -*-
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CviVendorDeliveryWizard(models.TransientModel):
    _name = "cvi.vendor.delivery.wizard"
    _inherit = ["cvi.wizard.mixin"]
    _description = "Entrega y devolución de mercadería de vendedores"

    vendor_id = fields.Many2one(
        "res.users",
        string="Vendedor",
        required=True,
        domain=lambda self: self._cvi_group_domain("group_cvi_vendor"),
    )
    direction = fields.Selection(
        selection=[("out", "Entrega al vendedor"), ("in", "Devolución a fábrica")],
        string="Operación",
        default="out",
        required=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Almacén",
        required=True,
        default=lambda self: self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        ),
    )
    line_ids = fields.One2many(
        "cvi.vendor.delivery.line", "wizard_id", string="Modelos y cantidades"
    )

    def _cvi_locations(self):
        """Ubicaciones origen y destino según la dirección de la operación."""
        self.ensure_one()
        factory = self.warehouse_id.lot_stock_id
        vendor = self.vendor_id._cvi_get_location()
        if self.direction == "out":
            return factory, vendor
        return vendor, factory

    def _cvi_check_availability(self, source):
        """Verifica que haya suficiente stock en el origen antes de mover nada (HU-02, HU-04)."""
        self.ensure_one()
        quant_model = self.env["stock.quant"]
        for line in self.line_ids:
            available = quant_model._get_available_quantity(line.product_id, source)
            if line.quantity > available:
                raise UserError(_(
                    "No hay suficiente stock de %(product)s en %(location)s: "
                    "pedís %(asked)s y hay %(available)s.",
                    product=line.product_id.display_name,
                    location=source.display_name,
                    asked=line.quantity,
                    available=available,
                ))

    def action_confirm_delivery(self):
        """Crea y valida el albarán que mueve la mercadería, y lo devuelve (HU-02, HU-04)."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Cargá al menos un modelo y su cantidad."))
        invalid = self.line_ids.filtered(lambda line: line.quantity <= 0)
        if invalid:
            raise UserError(_(
                "Estas líneas tienen cantidad cero o negativa: %s",
                ", ".join(invalid.mapped("product_id.display_name")),
            ))
        # _cvi_locations() necesita resolver la ubicación del vendedor (via
        # _cvi_get_location()) para saber origen/destino antes de poder chequear
        # disponibilidad, así que una entrega rechazada por falta de stock igual
        # puede provisionar la ubicación del vendedor como efecto colateral. Es
        # inofensivo e idempotente: no crea una ubicación nueva si ya existe.
        source, destination = self._cvi_locations()
        self._cvi_check_availability(source)
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse_id.int_type_id.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.vendor_id.partner_id.id,
            "origin": _("Mercadería de %s", self.vendor_id.name),
            "move_ids": [(0, 0, {
                "name": line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "product_uom": line.product_id.uom_id.id,
                "location_id": source.id,
                "location_dest_id": destination.id,
            }) for line in self.line_ids],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        # button_validate() puede devolver un wizard de backorder en lugar de dejar
        # el albarán en "done". No lo damos por hecho: si no quedó validado, la
        # entrega/devolución no se puede dar por concretada.
        if picking.state != "done":
            raise UserError(_(
                "No se pudo validar el albarán de %(direction)s de %(vendor)s: quedó "
                "en estado %(state)s. Revisá el stock antes de reintentar.",
                direction=dict(self._fields["direction"].selection)[self.direction],
                vendor=self.vendor_id.name,
                state=picking.state,
            ))
        _logger.info(
            "Mercadería %s: albarán %s de %s a %s",
            self.direction, picking.name, source.complete_name, destination.complete_name,
        )
        # Notificación + navegación al albarán: el usuario necesita una señal explícita
        # de que la entrega se concretó, no solo un cambio de pantalla.
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Entrega confirmada"),
                "message": _(
                    "Albarán %(picking)s: %(direction)s de %(vendor)s por %(units)s unidades.",
                    picking=picking.name,
                    direction=dict(self._fields["direction"].selection)[self.direction],
                    vendor=self.vendor_id.name,
                    units=sum(self.line_ids.mapped("quantity")),
                ),
                "next": {
                    "type": "ir.actions.act_window",
                    "name": _("Albarán generado"),
                    "res_model": "stock.picking",
                    "res_id": picking.id,
                    "view_mode": "form",
                    "target": "current",
                },
            },
        }


class CviVendorDeliveryLine(models.TransientModel):
    _name = "cvi.vendor.delivery.line"
    _description = "Línea de entrega o devolución de mercadería"

    wizard_id = fields.Many2one(
        "cvi.vendor.delivery.wizard", string="Operación", required=True, ondelete="cascade"
    )
    product_id = fields.Many2one(
        "product.product",
        string="Modelo de mueble",
        required=True,
        domain="[('is_storable', '=', True)]",
    )
    quantity = fields.Float(string="Cantidad", default=1.0, required=True)
