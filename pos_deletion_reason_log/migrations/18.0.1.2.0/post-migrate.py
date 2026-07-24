# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Baja el umbral de descuento alto de 35% a 30% en las cajas existentes.

    El default del campo pasó de 35.0 a 30.0, pero Odoo no reescribe defaults
    sobre filas existentes. Solo se actualizan las cajas que siguen en el
    default viejo (35), para no pisar umbrales configurados a mano.
    """
    cr.execute(
        """
        UPDATE pos_config
        SET high_discount_threshold = 30.0
        WHERE high_discount_threshold = 35.0
        """
    )
    _logger.info(
        "pos_deletion_reason_log: umbral de descuento alto bajado de 35%% a 30%% "
        "en %s caja(s)", cr.rowcount
    )
