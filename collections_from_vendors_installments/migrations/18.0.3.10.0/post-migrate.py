# -*- coding: utf-8 -*-
"""Marca la ubicación de retirados y cancela las cuotas de tarjetas ya retiradas.

Dos cosas que un `-u` no hace solo:

- El registro de la ubicación `Recuperados` vive en un bloque `noupdate="1"`, así
  que agregar `cvi_is_recovered_location` al XML no lo actualiza en una base que ya
  lo tenía creado. Sin esto el reporte de muebles retirados sale vacío.
- El estado de la cuota y el saldo de la tarjeta son computados almacenados: las
  tarjetas retiradas antes de esta versión siguen con sus cuotas en Pendiente o
  Vencida y con saldo vivo, hasta que algo las toque. El residual de cada cuota
  NO se toca: es el monto de la pérdida.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Sincroniza la marca de la ubicación y recalcula las tarjetas retiradas."""
    if not version:
        return
    cr.execute("""
        UPDATE stock_location SET cvi_is_recovered_location = TRUE
         WHERE id IN (
                 SELECT res_id FROM ir_model_data
                  WHERE module = 'collections_from_vendors_installments'
                    AND name = 'stock_location_recovered'
                    AND model = 'stock.location'
             )
           AND cvi_is_recovered_location IS NOT TRUE
    """)
    flagged = cr.rowcount

    env = api.Environment(cr, SUPERUSER_ID, {})
    installments = env["cvi.installment"].search([("card_id.state", "=", "recovered")])
    cards = installments.mapped("card_id")
    if installments:
        installments.invalidate_recordset(["amount_residual", "state"])
        installments._compute_amounts()
        installments._compute_state()
        cards.invalidate_recordset([
            "amount_paid", "amount_residual", "paid_installment_count",
            "pending_installment_count", "overdue_installment_count", "next_due_date",
            "days_overdue", "amount_overdue",
        ])
        cards._compute_balance()
        cards._compute_overdue_info()
    if flagged or installments:
        _logger.info(
            "Retirados: ubicación marcada (%s), cuotas canceladas %s en %s tarjetas",
            flagged, len(installments), len(cards),
        )
