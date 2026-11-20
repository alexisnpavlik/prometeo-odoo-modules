# -*- coding: utf-8 -*-

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

ALLOWED_PRICELISTS_PARAM = "pos_promotions.allowed_pricelist_ids"


class ProductTemplate(models.Model):
    _inherit = "product.template"

    is_promotion_pack = fields.Boolean("Es promoción", copy=False)
    promotion_pack_line_ids = fields.One2many(
        "pos.promotion.pack.line", "pack_tmpl_id", string="Productos de la promoción", copy=True
    )
    promotion_pack_regular_price = fields.Float(
        "Precio normal", compute="_compute_promotion_pack_prices", digits="Product Price"
    )
    promotion_pack_auto_price = fields.Float(
        "Último precio sugerido", copy=False, digits="Product Price",
        help="Suma que puso el formulario; si el precio sigue igual, se recalcula al cambiar productos.",
    )
    promotion_pack_saving = fields.Float(
        "Ahorro", compute="_compute_promotion_pack_prices", digits="Product Price"
    )
    promotion_pricelist_ids = fields.Many2many(
        "product.pricelist",
        "pos_promotion_pricelist_rel",
        "product_tmpl_id",
        "pricelist_id",
        string="Listas de precios",
        help="La promoción solo se aplica en el POS cuando la orden usa una de estas listas.",
    )
    promotion_allowed_pricelist_ids = fields.Many2many(
        "product.pricelist",
        compute="_compute_promotion_allowed_pricelist_ids",
        help="Listas que se pueden elegir: las permitidas en Ajustes y de la empresa de la promoción.",
    )

    @api.model
    def _promotion_allowed_pricelists(self):
        """Listas permitidas en Ajustes > Promociones; sin ninguna elegida, todas las activas."""
        pricelists = self.env["product.pricelist"].sudo()
        raw = self.env["ir.config_parameter"].sudo().get_param(ALLOWED_PRICELISTS_PARAM, "")
        ids = [int(value) for value in raw.split(",") if value.strip().isdigit()]
        if ids:
            return pricelists.browse(ids).exists().filtered("active")
        return pricelists.search([])

    @api.model
    def _promotion_default_pricelists(self, company=None):
        """Listas que trae una promoción nueva: las permitidas que el usuario puede ver
        (empresas activas) y que corresponden a la empresa de la promoción."""
        allowed = self._promotion_allowed_pricelists()
        domain = [("id", "in", allowed.ids)]
        if company:
            domain += ["|", ("company_id", "=", False), ("company_id", "=", company.id)]
        return self.env["product.pricelist"].search(domain)

    @api.depends("company_id")
    def _compute_promotion_allowed_pricelist_ids(self):
        """Opciones del campo Listas de precios. Una promoción con empresa solo puede usar
        listas de esa empresa o compartidas; una sin empresa, cualquiera permitida."""
        allowed = self._promotion_allowed_pricelists()
        for template in self:
            company = template.company_id
            options = allowed.filtered(lambda pl: not company or not pl.company_id or pl.company_id == company)
            template.promotion_allowed_pricelist_ids = [Command.set(options.ids)]

    @api.model
    def default_get(self, fields_list):
        """Una promoción nueva arranca con todas las listas permitidas seleccionadas."""
        res = super().default_get(fields_list)
        if "promotion_pricelist_ids" in fields_list and (
            res.get("is_promotion_pack") or self.env.context.get("default_is_promotion_pack")
        ):
            company = self.env["res.company"].browse(res.get("company_id"))
            res["promotion_pricelist_ids"] = [Command.set(self._promotion_default_pricelists(company or None).ids)]
        return res

    @api.depends("list_price", "promotion_pack_line_ids.quantity", "promotion_pack_line_ids.product_id.lst_price")
    def _compute_promotion_pack_prices(self):
        """Precio de los productos sueltos y cuánto se ahorra con el pack."""
        for template in self:
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            template.promotion_pack_regular_price = regular
            template.promotion_pack_saving = regular - template.list_price if regular else 0.0

    @api.onchange("promotion_pack_line_ids")
    def _onchange_promotion_pack_lines_price(self):
        """Precio del pack por defecto = suma de sus productos. Se recalcula mientras siga
        en el default de Odoo (1), en la última suma sugerida o quede más caro que los
        productos sueltos; un precio con descuento puesto a mano se respeta."""
        for template in self.filtered("is_promotion_pack"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            price = template.list_price
            if regular and (price <= 1 or price == template.promotion_pack_auto_price or price > regular):
                template.list_price = template.promotion_pack_auto_price = regular

    @api.constrains("is_promotion_pack", "list_price", "promotion_pack_line_ids")
    def _check_promotion_pack_price(self):
        """El pack no puede salir más caro que sus productos sueltos ni costar 1 o menos."""
        for template in self.filtered("is_promotion_pack"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            if template.list_price <= 1:
                raise ValidationError(_("Poné el precio de la promoción (no puede ser 1 o menos)."))
            if regular and template.list_price > regular:
                raise ValidationError(
                    _("La promoción no puede costar más que sus productos sueltos (%s).", round(regular, 2))
                )

    @api.constrains("is_promotion_pack", "promotion_pricelist_ids", "company_id")
    def _check_promotion_pricelists(self):
        """Al menos una lista, y de la empresa de la promoción si tiene una."""
        for template in self.filtered("is_promotion_pack"):
            pricelists = template.sudo().promotion_pricelist_ids
            if not pricelists:
                raise ValidationError(_("Elegí al menos una lista de precios para la promoción."))
            company = template.company_id
            if company and pricelists.filtered(lambda pl: pl.company_id and pl.company_id != company):
                raise ValidationError(
                    _("Una promoción de %s solo puede usar listas de esa empresa o compartidas.", company.name)
                )

    @api.constrains("is_promotion_pack", "promotion_pack_line_ids")
    def _check_promotion_pack_lines(self):
        """Un pack necesita al menos un producto."""
        if any(template.is_promotion_pack and not template.promotion_pack_line_ids for template in self):
            raise ValidationError(_("Agregá al menos un producto a la promoción."))

    @api.model_create_multi
    def create(self, vals_list):
        """El pack es un producto sin stock propio: en el POS se venden sus productos."""
        for vals in vals_list:
            if vals.get("is_promotion_pack"):
                vals.update(type="consu", is_storable=False)
                if not vals.get("promotion_pricelist_ids"):
                    company = self.env["res.company"].browse(vals.get("company_id"))
                    vals["promotion_pricelist_ids"] = [
                        Command.set(self._promotion_default_pricelists(company or None).ids)
                    ]
        return super().create(vals_list)
