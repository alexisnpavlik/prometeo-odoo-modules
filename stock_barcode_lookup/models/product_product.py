# -*- coding: utf-8 -*-

import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.misc import format_amount


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _barcode_lookup_price(self):
        """Precio de venta formateado con la moneda del producto."""
        return format_amount(self.env, self.lst_price, self.currency_id or self.env.company.currency_id)

    def _barcode_lookup_data(self, code):
        """Datos que muestra la tarjeta de resultado de la app Escáner."""
        template = self.product_tmpl_id
        # La foto puede guardarse en la plantilla (producto sin variantes): se usa la fecha más nueva
        last_write = max(self.write_date, template.write_date)
        return {
            "found": True,
            "code": code or self.barcode or self.default_code or "",
            "product_id": self.id,
            "template_id": template.id,
            "name": self.display_name,
            "price": self._barcode_lookup_price(),
            "qty_available": "%g" % self.qty_available,
            "uom": self.uom_id.name,
            "vendor": template.seller_ids[:1].partner_id.name or "",
            # unique evita que el navegador muestre la foto vieja tras sacar una nueva
            "image_url": "/web/image/product.product/%s/image_512?unique=%s"
            % (self.id, fields.Datetime.to_string(last_write).replace(" ", "_")),
            "can_replenish": bool(self.is_storable),
            "can_edit_qty": self._barcode_lookup_can_edit_qty(),
        }

    def _barcode_lookup_can_edit_qty(self):
        """Editar la cantidad solo para responsables de Inventario y productos sin lote/serie."""
        return bool(
            self.is_storable
            and self.tracking == "none"
            and self.env.user.has_group("stock.group_stock_manager")
        )

    def _barcode_lookup_adjust_target(self):
        """Quant existente (o False) y ubicación a ajustar en la empresa activa.

        Va a la ubicación interna donde ya hay stock; si no hay, al stock del
        almacén principal. Si está repartido en varias ubicaciones no se adivina
        dónde sumar o restar: se pide ajustarlo desde Inventario.
        """
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        company = self.env.company
        quants = Quant.search([
            ("product_id", "=", self.id),
            ("company_id", "=", company.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", "!=", 0),
        ])
        if len(quants.location_id) > 1:
            raise UserError(_(
                "El stock de «%(product)s» está repartido en varias ubicaciones (%(locations)s). "
                "Ajustalo desde Inventario > Ajustes físicos.",
                product=self.display_name,
                locations=", ".join(quants.location_id.mapped("display_name")),
            ))
        if quants:
            return quants[:1], quants.location_id
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
        if not warehouse:
            raise UserError(_("La empresa %s no tiene almacén.", company.name))
        location = warehouse.lot_stock_id
        quant = Quant.search([("product_id", "=", self.id), ("location_id", "=", location.id)], limit=1)
        return quant, location

    def _barcode_lookup_check_can_edit_qty(self):
        """Mismos chequeos para mostrar el formulario y para guardar."""
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise AccessError(_("Solo un responsable de Inventario puede editar la cantidad."))
        if not self.is_storable:
            raise UserError(_("«%s» no lleva control de stock.", self.display_name))
        if self.tracking != "none":
            raise UserError(_("«%s» se controla por lote o serie: ajustalo desde Inventario.", self.display_name))

    @api.model
    def barcode_lookup_quantity_target(self, product_id):
        """Ubicación y cantidad actual que edita "Editar cantidad" (la tarjeta suma todas las sucursales)."""
        product = self.browse(product_id).exists()
        if not product:
            raise UserError(_("El producto ya no existe."))
        product._barcode_lookup_check_can_edit_qty()
        quant, location = product._barcode_lookup_adjust_target()
        return {
            "location": location.display_name,
            "company": self.env.company.name,
            "quantity": quant.quantity if quant else 0.0,
        }

    @api.model
    def barcode_lookup_set_quantity(self, product_id, quantity):
        """Fija el stock contado de un producto (ajuste de inventario) desde la app Escáner."""
        product = self.browse(product_id).exists()
        if not product:
            raise UserError(_("El producto ya no existe."))
        product._barcode_lookup_check_can_edit_qty()
        quantity = float(quantity)
        if quantity < 0:
            raise UserError(_("La cantidad no puede ser negativa."))
        quant, location = product._barcode_lookup_adjust_target()
        if quant:
            quant.inventory_quantity = quantity
        else:
            quant = self.env["stock.quant"].with_context(inventory_mode=True).create({
                "product_id": product.id,
                "location_id": location.id,
                "inventory_quantity": quantity,
            })
        # Sin auto_apply, action_apply_inventory puede devolver un wizard y no aplicar nada
        quant.with_context(inventory_mode=True, set_inventory_quantity_auto_apply=True).action_apply_inventory()
        return product._barcode_lookup_data(False)

    @api.model
    def barcode_lookup(self, code):
        """Busca un producto por código de barras (o referencia) exacto para la app Escáner."""
        code = (code or "").strip()
        if not code:
            return {"found": False, "code": code, "is_code": True}
        product = self.search([("barcode", "=", code)], limit=1) or self.search(
            [("default_code", "=", code)], limit=1
        )
        if not product:
            # Sin letras ni espacios se trata como código; si no, como nombre (para "Crear producto")
            is_code = not re.search(r"[^\W\d_]|\s", code)
            return {"found": False, "code": code, "is_code": is_code}
        return product._barcode_lookup_data(code)

    @api.model
    def barcode_lookup_product(self, product_id):
        """Tarjeta de resultado para un producto elegido de la lista de búsqueda."""
        product = self.browse(product_id).exists()
        if not product:
            return {"found": False, "code": "", "is_code": True}
        return product._barcode_lookup_data(False)

    @api.model
    def barcode_lookup_search(self, term, limit=20):
        """Busca productos por nombre, código de barras o referencia (coincidencia parcial)."""
        term = (term or "").strip()
        if len(term) < 2:
            return []
        domain = ["|", "|", ("name", "ilike", term), ("barcode", "ilike", term), ("default_code", "ilike", term)]
        products = self.search(domain, limit=limit, order="name")
        return [
            {
                "product_id": product.id,
                "name": product.display_name,
                "code": product.barcode or product.default_code or "",
                "price": product._barcode_lookup_price(),
                "image_url": "/web/image/product.product/%s/image_128" % product.id,
            }
            for product in products
        ]
