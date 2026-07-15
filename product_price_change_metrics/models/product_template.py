# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def write(self, vals):
        """Registra un cambio de precio global (list_price) para cada empresa."""
        track_price = "list_price" in vals
        old_prices = {}
        if track_price and not self.env.context.get("install_mode"):
            for record in self:
                old_prices[record.id] = record.list_price
        res = super().write(vals)
        if old_prices:
            try:
                self._ppcm_log_global_change(old_prices)
            except Exception as e:
                _logger.warning(
                    "product_price_change_metrics: fallo al registrar cambio global en %s: %s",
                    self, e,
                )
        return res

    def _ppcm_log_global_change(self, old_prices):
        """Crea una fila de log global (fan-out a todas las empresas) por producto cambiado."""
        companies = self.env["res.company"].sudo().search([])
        Log = self.env["product.price.log"].sudo()
        for record in self:
            old = old_prices.get(record.id)
            new = record.list_price
            if old is None or old == new:
                continue
            Log._log_change({
                "product_tmpl_id": record.id,
                "source": "global",
                "price_type": "fixed",
                "old_price": old,
                "new_price": new,
                "user_id": self.env.uid,
            }, companies)
