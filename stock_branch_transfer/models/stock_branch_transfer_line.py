from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockBranchTransferLine(models.Model):
    _name = "stock.branch.transfer.line"
    _description = "Línea de traslado entre sucursales"

    transfer_id = fields.Many2one(
        "stock.branch.transfer", string="Traslado", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto",
        required=True,
        domain=[
            ("company_id", "=", False),
            ("type", "=", "consu"),
            ("is_storable", "=", True),
            ("tracking", "=", "none"),
        ],
    )
    uom_id = fields.Many2one(related="product_id.uom_id", string="Unidad")
    qty_sent = fields.Float(string="Enviado", digits="Product Unit of Measure")
    qty_received = fields.Float(string="Recibido", digits="Product Unit of Measure")
    qty_available_origin = fields.Float(
        string="Stock en origen", compute="_compute_qty_available_origin", digits="Product Unit of Measure"
    )

    qty_available_dest = fields.Float(
        string="Stock en destino", compute="_compute_qty_available_dest", digits="Product Unit of Measure"
    )

    sale_price = fields.Float(string="Precio de venta", compute="_compute_sale_price", digits="Product Price")

    @api.depends("product_id", "transfer_id.dest_company_id")
    def _compute_sale_price(self):
        """Precio en la lista de la sucursal destino; sin regla para el producto, el precio de venta de la ficha."""
        Pricelist = self.env["product.pricelist"].sudo()
        for line in self:
            product = line.product_id
            price = product.lst_price
            pricelists = Pricelist.search([("company_id", "=", line.transfer_id.dest_company_id.id)])
            for pricelist in pricelists:
                if pricelist._get_product_rule(product, 1.0):
                    price = pricelist._get_product_price(product, 1.0)
                    break
            line.sale_price = price

    def _company_stock(self, company):
        """Stock actual del producto de la línea en la ubicación de stock de la empresa."""
        if not self.product_id or not company:
            return 0.0
        location = self.transfer_id._stock_location(company)
        quants = self.env["stock.quant"].sudo().search(
            [("product_id", "=", self.product_id.id), ("location_id", "child_of", location.id)]
        )
        return sum(quants.mapped("quantity"))

    @api.depends("product_id", "transfer_id.company_id")
    def _compute_qty_available_origin(self):
        """Stock actual del producto en la sucursal de origen (aviso, no bloquea)."""
        for line in self:
            line.qty_available_origin = line._company_stock(line.transfer_id.company_id)

    @api.depends("product_id", "transfer_id.dest_company_id")
    def _compute_qty_available_dest(self):
        """Stock actual del producto en la sucursal de destino (referencia para decidir el envío)."""
        for line in self:
            line.qty_available_dest = line._company_stock(line.transfer_id.dest_company_id)

    @api.constrains("product_id")
    def _check_product(self):
        """Sin lotes/series ni productos propios de una empresa."""
        for line in self:
            if line.product_id.tracking != "none":
                raise UserError(_("%s usa lotes o números de serie: no se puede trasladar.", line.product_id.display_name))
            if line.product_id.company_id:
                raise UserError(_("%s pertenece a una sola empresa: no se puede trasladar.", line.product_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        """Una línea nueva en un traslado ya enviado la agrega un manager y mueve stock."""
        lines = super().create(vals_list)
        lines.transfer_id._after_line_change(self.env.context)
        return lines

    def write(self, vals):
        """Cambiar cantidades o producto de un traslado ya enviado corrige el stock."""
        res = super().write(vals)
        if {"product_id", "qty_sent", "qty_received"} & set(vals):
            self.transfer_id._after_line_change(self.env.context)
        return res

    def unlink(self):
        """Quitar una línea de un traslado ya enviado devuelve su stock."""
        transfers = self.transfer_id
        transfers._before_line_change(self.env.context)
        res = super().unlink()
        transfers._after_line_change(self.env.context, checked=True)
        return res
