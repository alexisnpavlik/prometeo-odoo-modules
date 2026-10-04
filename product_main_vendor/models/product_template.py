from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    main_vendor_id = fields.Many2one(
        "res.partner",
        string="Proveedor",
        compute="_compute_main_vendor_id",
        inverse="_inverse_main_vendor_id",
        help="Primer proveedor de la pestaña Compras. Elegir otro lo pone "
             "primero en esa lista; vaciarlo no borra ninguna línea.",
    )

    def _general_sellers(self):
        """Líneas de proveedor que aplican a todas las variantes, en el orden de Odoo."""
        self.ensure_one()
        return self.seller_ids.filtered(lambda s: not s.product_id).sorted(
            lambda s: (s.sequence, s.id))

    @api.depends("seller_ids.sequence", "seller_ids.partner_id", "seller_ids.product_id")
    def _compute_main_vendor_id(self):
        """Proveedor de la línea con menor secuencia."""
        for template in self:
            template.main_vendor_id = template._general_sellers()[:1].partner_id

    def _inverse_main_vendor_id(self):
        """Pone primero la línea del proveedor elegido, creándola si no existe.

        Se renumera la secuencia de todas las líneas en vez de usar un valor
        menor al mínimo: así no aparecen secuencias negativas y el resto
        conserva su orden relativo.
        """
        for template in self:
            vendor = template.main_vendor_id
            if not vendor:
                # Sin esto la caché sigue en vacío aunque la línea siga ahí.
                template.invalidate_recordset(["main_vendor_id"])
                continue
            sellers = template._general_sellers()
            chosen = sellers.filtered(lambda s: s.partner_id == vendor)
            # Si el proveedor tiene líneas en varias compañías, se prefiere la propia.
            chosen = (chosen.filtered(lambda s: s.company_id == self.env.company)
                      or chosen)[:1]
            if not chosen:
                chosen = self.env["product.supplierinfo"].create({
                    "partner_id": vendor.id,
                    "product_tmpl_id": template.id,
                    "price": template.standard_price,
                    "company_id": self.env.company.id,
                })
            for sequence, seller in enumerate(chosen | (sellers - chosen), start=1):
                if seller.sequence != sequence:
                    seller.sequence = sequence
