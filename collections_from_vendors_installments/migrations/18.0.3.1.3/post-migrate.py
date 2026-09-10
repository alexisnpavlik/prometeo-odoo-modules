# -*- coding: utf-8 -*-
"""Repara contadores de visitas guardadas desde el formulario antes de esta versión."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Recuenta las líneas sin cambiar el resultado manual ni el historial de cierre."""
    if not version:
        return
    cr.execute("""
        UPDATE cvi_supervision_visit AS visit
           SET card_count = counts.cards,
               issue_count = counts.issues
          FROM (
              SELECT v.id, COUNT(l.id) AS cards,
                     COUNT(l.id) FILTER (WHERE l.has_issue) AS issues
                FROM cvi_supervision_visit v
                LEFT JOIN cvi_supervision_line l ON l.visit_id = v.id
               GROUP BY v.id
          ) AS counts
         WHERE visit.id = counts.id
           AND (visit.card_count IS DISTINCT FROM counts.cards
                OR visit.issue_count IS DISTINCT FROM counts.issues)
    """)
    _logger.info("Contadores de supervisión corregidos: %s visitas", cr.rowcount)
