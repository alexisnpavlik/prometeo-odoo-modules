# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PosControlLog(models.Model):
    _name = "pos.control.log"
    _description = "Registro de trazabilidad de operaciones POS"
    _order = "event_datetime desc, id desc"

    event_type = fields.Selection(
        [
            ("order", "Orden eliminada"),
            ("line", "Línea eliminada"),
            ("qty_reduction", "Reducción de cantidad"),
            ("high_discount", "Descuento alto"),
            ("price_reduction", "Reducción de precio"),
        ],
        string="Tipo",
        required=True,
    )
    user_id = fields.Many2one("res.users", string="Cajero", required=True)
    pos_config_id = fields.Many2one("pos.config", string="Punto de venta")
    session_id = fields.Many2one("pos.session", string="Sesión")
    order_ref = fields.Char(string="Referencia de orden")
    product_id = fields.Many2one("product.product", string="Producto")
    qty_removed = fields.Float(string="Cantidad quitada")
    amount_removed = fields.Float(string="Importe afectado")
    discount_percent = fields.Float(string="Descuento (%)")
    old_price = fields.Float(string="Precio anterior")
    new_price = fields.Float(string="Precio nuevo")
    reason_id = fields.Many2one("pos.deletion.reason", string="Motivo")
    reason_note = fields.Text(string="Nota")
    event_datetime = fields.Datetime(
        string="Fecha/hora", default=fields.Datetime.now, required=True
    )
    company_id = fields.Many2one(
        "res.company", string="Compañía", default=lambda self: self.env.company
    )

    @api.model
    def log_event(self, vals):
        """Crea un registro de trazabilidad. Llamado desde el POS por RPC.

        Se ejecuta en sudo porque el cajero no tiene create directo sobre el
        modelo. Completa cajero (usuario actual) y fecha si no vinieron.
        """
        allowed = {
            "event_type",
            "pos_config_id",
            "session_id",
            "order_ref",
            "product_id",
            "qty_removed",
            "amount_removed",
            "discount_percent",
            "old_price",
            "new_price",
            "reason_id",
            "reason_note",
        }
        clean = {k: v for k, v in (vals or {}).items() if k in allowed}
        clean["user_id"] = self.env.user.id
        record = self.sudo().create(clean)
        _logger.info(
            "POS control log %s: type=%s user=%s product=%s",
            record.id, clean.get("event_type"), record.user_id.id, clean.get("product_id"),
        )
        return record.id
