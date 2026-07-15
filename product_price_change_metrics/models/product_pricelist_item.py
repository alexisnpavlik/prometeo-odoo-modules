# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

_PRICE_FIELDS = ("fixed_price", "percent_price", "compute_price")


class ProductPricelistItem(models.Model):
    _inherit = "product.pricelist.item"

    def _ppcm_price_snapshot(self):
        """Devuelve (price_type, precio) comparable del item, o None si no aplica."""
        self.ensure_one()
        if self.applied_on not in ("1_product", "0_product_variant"):
            return None
        if self.compute_price == "fixed":
            return ("fixed", self.fixed_price or 0.0)
        if self.compute_price == "percentage":
            return ("percent", self.percent_price or 0.0)
        return None  # formula u otros: no comparable

    def write(self, vals):
        """Registra un cambio de precio de item de lista para la empresa dueña."""
        track = any(f in vals for f in _PRICE_FIELDS) and not self.env.context.get("install_mode")
        old_state = {}
        if track:
            for item in self:
                old_state[item.id] = item._ppcm_price_snapshot()
        res = super().write(vals)
        if track:
            try:
                self._ppcm_log_item_change(old_state)
            except Exception as e:
                _logger.warning(
                    "product_price_change_metrics: fallo al registrar cambio de lista en %s: %s",
                    self, e,
                )
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """Registra el alta de un item de lista con precio concreto."""
        items = super().create(vals_list)
        if not self.env.context.get("install_mode"):
            try:
                items._ppcm_log_item_change({})
            except Exception as e:
                _logger.warning(
                    "product_price_change_metrics: fallo al registrar alta de lista: %s", e,
                )
        return items

    def _ppcm_log_item_change(self, old_state):
        """Crea la fila de log del item cambiado, para la empresa de su lista (o fan-out)."""
        Log = self.env["product.price.log"].sudo()
        all_companies = None
        for item in self:
            snap = item._ppcm_price_snapshot()
            if snap is None:
                continue
            old = old_state.get(item.id)
            if old is not None and old == snap:
                continue
            price_type, new_price = snap
            if old is None and not new_price:
                # Alta de item sin precio real (placeholder $0): no ensuciar la checklist.
                continue
            tmpl = item.product_tmpl_id or item.product_id.product_tmpl_id
            if not tmpl:
                continue
            old_price = old[1] if old else 0.0
            company = item.pricelist_id.company_id
            if company:
                companies = company
            else:
                if all_companies is None:
                    all_companies = self.env["res.company"].sudo().search([])
                companies = all_companies
            Log._log_change({
                "product_tmpl_id": tmpl.id,
                "product_id": item.product_id.id if item.product_id else False,
                "source": "pricelist",
                "pricelist_id": item.pricelist_id.id,
                "price_type": price_type,
                "old_price": old_price,
                "new_price": new_price,
                "user_id": self.env.uid,
            }, companies)
