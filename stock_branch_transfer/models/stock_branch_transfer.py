import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

STATES = [
    ("draft", "Borrador"),
    ("in_transit", "En camino"),
    ("received", "Recibido"),
    ("with_diff", "Con diferencias"),
    ("closed", "Cerrado"),
    ("cancel", "Anulado"),
]


class StockBranchTransfer(models.Model):
    _name = "stock.branch.transfer"
    _description = "Traslado entre sucursales"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(string="Número", default="Nuevo", readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", string="Origen", required=True, default=lambda self: self.env.company, tracking=True
    )
    dest_company_id = fields.Many2one("res.company", string="Destino", required=True, tracking=True)
    state = fields.Selection(STATES, string="Estado", default="draft", required=True, copy=False, tracking=True)
    user_id = fields.Many2one("res.users", string="Creado por", default=lambda self: self.env.user, readonly=True)
    date_sent = fields.Datetime(string="Fecha de envío", readonly=True, copy=False)
    date_received = fields.Datetime(string="Fecha de recepción", readonly=True, copy=False)
    diff_note = fields.Text(string="Nota de diferencias", copy=False)
    line_ids = fields.One2many("stock.branch.transfer.line", "transfer_id", string="Productos", copy=True)
    picking_ids = fields.One2many("stock.picking", "branch_transfer_id", string="Movimientos", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna el número de secuencia TRS/ al crear."""
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("stock.branch.transfer") or "Nuevo"
        return super().create(vals_list)

    @api.constrains("company_id", "dest_company_id")
    def _check_dest_company(self):
        """El destino tiene que ser otra sucursal."""
        for transfer in self:
            if transfer.company_id == transfer.dest_company_id:
                raise ValidationError(_("La sucursal destino tiene que ser distinta de la de origen."))
