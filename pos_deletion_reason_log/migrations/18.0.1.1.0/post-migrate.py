# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Enciende los toggles de motivo en las cajas ya existentes.

    Los campos require_reason_order_deletion / _line_deletion / _qty_reduction
    se agregaron sin default (columna creada en False) y recién después se les
    puso default=True. Odoo no reescribe defaults sobre filas existentes, así
    que las cajas creadas antes quedaron con esos toggles en False y el POS no
    pedía motivo al eliminar/cancelar orden (incluido el cierre de caja).

    Esta migración los pone en True una única vez (solo donde están en False),
    alineándolos con el default y con discount/price que sí nacieron en True.
    """
    cr.execute(
        """
        UPDATE pos_config
        SET require_reason_order_deletion = TRUE
        WHERE require_reason_order_deletion IS NOT TRUE
        """
    )
    cr.execute(
        """
        UPDATE pos_config
        SET require_reason_line_deletion = TRUE
        WHERE require_reason_line_deletion IS NOT TRUE
        """
    )
    cr.execute(
        """
        UPDATE pos_config
        SET require_reason_qty_reduction = TRUE
        WHERE require_reason_qty_reduction IS NOT TRUE
        """
    )
    _logger.info(
        "pos_deletion_reason_log: toggles de motivo (order/line/qty) encendidos "
        "en cajas existentes"
    )
