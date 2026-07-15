import logging

from odoo import _, models
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    @staticmethod
    def _pch_fmt_qty(qty):
        """Formatea una cantidad sin ceros/decimales sobrantes (5.0 -> 5)."""
        return ("%g" % (qty or 0.0))

    def _apply_inventory(self):
        """Registra el ajuste de inventario en el chatter de la plantilla.

        Se capturan los valores antes de aplicar (cantidad vieja, nueva y
        ubicacion) y luego se postea una nota en el product.template afectado.
        """
        snapshots = []
        for quant in self:
            rounding = quant.product_uom_id.rounding
            if float_is_zero(quant.inventory_diff_quantity, precision_rounding=rounding):
                continue
            snapshots.append(
                {
                    "template": quant.product_id.product_tmpl_id,
                    "product": quant.product_id,
                    "old_qty": quant.quantity,
                    "new_qty": quant.inventory_quantity,
                    "uom": quant.product_uom_id.name or "",
                    "location": quant.location_id.display_name or "",
                    "lot": quant.lot_id.name or "",
                }
            )

        res = super()._apply_inventory()

        for snap in snapshots:
            template = snap["template"]
            if not template:
                continue
            variant = ""
            if snap["product"] != template.product_variant_id or template.product_variant_count > 1:
                variant = _(" (variante %s)", snap["product"].display_name)
            lot = _(" [lote %s]", snap["lot"]) if snap["lot"] else ""
            body = _(
                "Ajuste de inventario%(variant)s%(lot)s: %(old)s → %(new)s %(uom)s en %(loc)s",
                variant=variant,
                lot=lot,
                old=self._pch_fmt_qty(snap["old_qty"]),
                new=self._pch_fmt_qty(snap["new_qty"]),
                uom=snap["uom"],
                loc=snap["location"],
            )
            template.message_post(body=body)

        return res
