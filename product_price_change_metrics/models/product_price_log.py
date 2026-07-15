# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ProductPriceLog(models.Model):
    _name = "product.price.log"
    _description = "Cambio de precio para actualización de góndola"
    _order = "change_date desc, id desc"

    product_tmpl_id = fields.Many2one(
        "product.template", string="Producto", required=True,
        ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(
        "product.product", string="Variante", ondelete="cascade", index=True,
    )
    source = fields.Selection(
        [("global", "Precio global"), ("pricelist", "Lista de precios")],
        string="Origen", required=True,
    )
    pricelist_id = fields.Many2one("product.pricelist", string="Lista de precios")
    company_id = fields.Many2one(
        "res.company", string="Empresa", required=True, index=True,
    )
    price_type = fields.Selection(
        [("fixed", "Fijo"), ("percent", "Porcentaje")], string="Tipo de precio",
    )
    old_price = fields.Float(string="Precio anterior")
    new_price = fields.Float(string="Precio nuevo")
    diff_amount = fields.Float(
        string="Diferencia", compute="_compute_diff_amount", store=True,
    )
    change_date = fields.Datetime(
        string="Fecha de cambio", default=fields.Datetime.now, index=True,
    )
    user_id = fields.Many2one(
        "res.users", string="Modificado por", default=lambda self: self.env.user,
    )
    state = fields.Selection(
        [("pending", "Pendiente"), ("done", "Actualizado")],
        string="Estado góndola", default="pending", required=True, index=True,
    )
    done_user_id = fields.Many2one("res.users", string="Actualizado por")
    done_date = fields.Datetime(string="Fecha actualización")

    @api.depends("old_price", "new_price")
    def _compute_diff_amount(self):
        """Diferencia absoluta entre precio nuevo y anterior."""
        for rec in self:
            rec.diff_amount = (rec.new_price or 0.0) - (rec.old_price or 0.0)

    @api.model
    def _log_change(self, vals, companies):
        """Crea una fila de log por cada empresa (fan-out). `vals` sin company_id."""
        logs = self.browse()
        for company in companies:
            logs |= self.sudo().create(dict(vals, company_id=company.id))
        return logs
