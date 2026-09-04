# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import logging
from collections import defaultdict

from odoo import models
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _create_move_from_pos_order_lines(self, lines):
        """Descuenta stock de los componentes en lugar del pack.

        - `non_detailed`: el pack viaja en una sola línea, así que se generan
          los movimientos de todos sus componentes.
        - `detailed`: el frontend explota el pack en una línea por componente y
          esas líneas ya mueven stock por el camino normal. Acá solo se cubre
          el faltante, para el caso en que el POS no haya podido crear alguna
          de esas líneas (componente fuera del set precargado, por ejemplo).

        El pack en sí nunca genera movimiento: lo que sale del depósito son
        los componentes.
        """
        self.ensure_one()

        normal_lines = self.env["pos.order.line"]
        non_detailed_lines = self.env["pos.order.line"]
        detailed_lines = self.env["pos.order.line"]

        for line in lines:
            if not line.product_id.pack_ok:
                normal_lines |= line
            elif line.product_id.pack_type == "non_detailed":
                non_detailed_lines |= line
            else:
                detailed_lines |= line

        # Handle normal lines using original logic
        if normal_lines:
            super()._create_move_from_pos_order_lines(normal_lines)

        move_vals = []
        for line in non_detailed_lines:
            for comp_product, qty in self._get_pack_component_qties(line).items():
                move_vals.extend(
                    self._prepare_pack_component_move_vals(line, comp_product, qty)
                )
        move_vals.extend(
            self._prepare_uncovered_pack_component_move_vals(detailed_lines, lines)
        )

        if move_vals:
            moves = self.env["stock.move"].create(move_vals)
            confirmed_moves = moves._action_confirm()
            # Odoo's _add_mls_related_to_order will handle moves whose product_id is not in lines
            confirmed_moves._add_mls_related_to_order(lines, are_qties_done=True)
            confirmed_moves.picked = True

    def _get_pack_component_qties(self, line):
        """Cantidades de cada componente para una línea de pack."""
        qties = defaultdict(float)
        for pack_line in line.product_id.pack_line_ids:
            qties[pack_line.product_id] += abs(line.qty * pack_line.quantity)
        return qties

    def _prepare_pack_component_move_vals(self, line, comp_product, qty):
        """Valores del movimiento de un componente, si corresponde crearlo."""
        # Only create stock moves for consumable/storable products
        if comp_product.type != "consu":
            return []
        if float_is_zero(qty, precision_rounding=comp_product.uom_id.rounding):
            return []
        return [
            {
                "name": f"{line.name} - {comp_product.name}",
                "product_uom": comp_product.uom_id.id,
                "picking_id": self.id,
                "picking_type_id": self.picking_type_id.id,
                "product_id": comp_product.id,
                "product_uom_qty": qty,
                "location_id": self.location_id.id,
                "location_dest_id": self.location_dest_id.id,
                "company_id": self.company_id.id,
            }
        ]

    def _prepare_uncovered_pack_component_move_vals(self, detailed_lines, lines):
        """Red de seguridad para los packs `detailed`.

        Compara lo que el pack debería descontar contra las líneas de
        componente que el POS realmente creó (`is_pack_component`) y devuelve
        los movimientos del faltante. Las líneas sueltas del mismo producto no
        cuentan como cobertura: son una venta aparte.
        """
        if not detailed_lines:
            return []

        expected = defaultdict(float)
        source_line = {}
        for line in detailed_lines:
            for comp_product, qty in self._get_pack_component_qties(line).items():
                expected[comp_product] += qty
                source_line.setdefault(comp_product, line)

        covered = defaultdict(float)
        for line in lines:
            if line.is_pack_component:
                covered[line.product_id] += abs(line.qty)

        move_vals = []
        for comp_product, qty in expected.items():
            missing = qty - covered.get(comp_product, 0.0)
            rounding = comp_product.uom_id.rounding
            if float_compare(missing, 0.0, precision_rounding=rounding) <= 0:
                continue
            _logger.info(
                "Pack %s: falta la línea de %s en %s, se descuenta %s desde el pack",
                source_line[comp_product].product_id.display_name,
                comp_product.display_name,
                self.name,
                missing,
            )
            move_vals.extend(
                self._prepare_pack_component_move_vals(
                    source_line[comp_product], comp_product, missing
                )
            )
        return move_vals
