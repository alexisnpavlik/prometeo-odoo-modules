# -*- coding: utf-8 -*-

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError

ALLOWED_COMPANIES_PARAM = "pos_promotions.allowed_company_ids"


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
    promotion_price_mode = fields.Selection(
        [("fixed", "Precio fijo"), ("percent", "% de descuento")],
        string="Tipo de promoción",
        default="fixed",
        required=True,
        help="Precio fijo: la promoción cuesta lo mismo en todas sus listas. "
        "% de descuento: se descuenta sobre el precio de la lista de cada sucursal.",
    )
    promotion_discount_percent = fields.Float(
        "Descuento (%)", digits=(5, 2),
        help="Porcentaje que se descuenta del precio de la lista de la orden.",
    )
    promotion_list_price_ids = fields.One2many(
        "pos.promotion.price", "pack_tmpl_id", string="Precio por sucursal", copy=True,
        help="Precio puntual de la promoción en una sucursal. Pisa al tipo de promoción solo ahí.",
    )
    promotion_use_dates = fields.Boolean(
        "Tiene vigencia", compute="_compute_promotion_use_dates", store=True, readonly=False,
        help="Marcalo para cargar desde y hasta cuándo vale. Sin marcar, vale siempre mientras esté activa.",
    )
    promotion_date_start = fields.Date(
        "Válida desde", help="Opcional. Vacío: vale desde ya.",
    )
    promotion_date_end = fields.Date(
        "Válida hasta", help="Opcional, inclusive. Vacío: no vence.",
    )
    promotion_company_ids = fields.Many2many(
        "res.company",
        "pos_promotion_company_rel",
        "product_tmpl_id",
        "company_id",
        string="Sucursales",
        help="La promoción se aplica en las cajas de estas sucursales, sobre el precio de su lista.",
    )
    promotion_allowed_company_ids = fields.Many2many(
        "res.company",
        compute="_compute_promotion_allowed_company_ids",
        help="Sucursales que se pueden elegir: las permitidas en Ajustes y la de la promoción.",
    )

    @api.model
    def _promotion_allowed_companies(self):
        """Sucursales permitidas en Ajustes > Promociones; sin ninguna elegida, todas."""
        companies = self.env["res.company"].sudo()
        raw = self.env["ir.config_parameter"].sudo().get_param(ALLOWED_COMPANIES_PARAM, "")
        ids = [int(value) for value in raw.split(",") if value.strip().isdigit()]
        return companies.browse(ids).exists() if ids else companies.search([])

    @api.model
    def _promotion_default_companies(self, company=None):
        """Sucursales que trae una promoción nueva: las permitidas y activas en el
        selector de empresas; si la promoción tiene empresa, solo esa."""
        companies = self._promotion_allowed_companies() & self.env.companies
        return companies & company if company else companies

    @api.depends("company_id")
    @api.depends_context("uid")
    def _compute_promotion_allowed_company_ids(self):
        """Opciones del campo Sucursales: las permitidas a las que el usuario tiene acceso
        (el formulario muestra sus nombres); con empresa en la promoción, solo esa."""
        allowed = self._promotion_allowed_companies() & self.env.user.company_ids
        for template in self:
            options = allowed & template.company_id if template.company_id else allowed
            template.promotion_allowed_company_ids = [Command.set(options.ids)]

    @api.model
    def default_get(self, fields_list):
        """Una promoción nueva arranca con todas las sucursales permitidas seleccionadas."""
        res = super().default_get(fields_list)
        if "promotion_company_ids" in fields_list and (
            res.get("is_promotion_pack") or self.env.context.get("default_is_promotion_pack")
        ):
            company = self.env["res.company"].browse(res.get("company_id"))
            res["promotion_company_ids"] = [Command.set(self._promotion_default_companies(company or None).ids)]
        return res

    @api.depends(
        "list_price", "promotion_price_mode", "promotion_discount_percent",
        "promotion_pack_line_ids.quantity", "promotion_pack_line_ids.product_id.lst_price",
    )
    def _compute_promotion_pack_prices(self):
        """Precio de venta de los productos sueltos y cuánto se ahorra (referencia: en el
        POS manda el precio de la lista de cada sucursal)."""
        for template in self:
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            template.promotion_pack_regular_price = regular
            if not regular:
                template.promotion_pack_saving = 0.0
            elif template.promotion_price_mode == "percent":
                template.promotion_pack_saving = regular * template.promotion_discount_percent / 100
            else:
                template.promotion_pack_saving = regular - template.list_price

    @api.onchange("promotion_pack_line_ids", "promotion_price_mode", "promotion_discount_percent")
    def _onchange_promotion_pack_lines_price(self):
        """Precio del pack por defecto = suma de sus productos. Se recalcula mientras siga
        en el default de Odoo (1), en la última suma sugerida o quede más caro que los
        productos sueltos; un precio con descuento puesto a mano se respeta."""
        for template in self.filtered("is_promotion_pack"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            if template.promotion_price_mode == "percent":
                # Precio de referencia que muestra la tarjeta del POS; el real sale de la lista.
                if regular:
                    template.list_price = round(regular * (1 - template.promotion_discount_percent / 100), 2)
                continue
            price = template.list_price
            if regular and (price <= 1 or price == template.promotion_pack_auto_price or price > regular):
                template.list_price = template.promotion_pack_auto_price = regular

    @api.constrains("is_promotion_pack", "list_price", "promotion_pack_line_ids", "promotion_price_mode",
                    "promotion_discount_percent")
    def _check_promotion_pack_price(self):
        """Precio fijo: ni 1 o menos ni más caro que los productos sueltos. %: entre 0 y 100."""
        for template in self.filtered("is_promotion_pack"):
            if template.promotion_price_mode == "percent":
                if not 0 < template.promotion_discount_percent < 100:
                    raise ValidationError(_("El descuento tiene que ser mayor a 0 y menor a 100%."))
                continue
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            if template.list_price <= 1:
                raise ValidationError(_("Poné el precio de la promoción (no puede ser 1 o menos)."))
            if regular and template.list_price > regular:
                raise ValidationError(
                    _("La promoción no puede costar más que sus productos sueltos (%s).", round(regular, 2))
                )

    @api.constrains("is_promotion_pack", "promotion_company_ids", "company_id", "promotion_list_price_ids")
    def _check_promotion_companies(self):
        """Al menos una sucursal; los precios por sucursal, de sucursales elegidas; y si la
        promoción tiene empresa, solo esa."""
        for template in self.filtered("is_promotion_pack"):
            companies = template.sudo().promotion_company_ids
            if not companies:
                raise ValidationError(_("Elegí al menos una sucursal para la promoción."))
            orphan = template.sudo().promotion_list_price_ids.company_id - companies
            if orphan:
                raise ValidationError(
                    _("%s tiene un precio en Precio por sucursal pero no está en las sucursales de la promoción: agregala o borrá ese precio.",
                      ", ".join(orphan.mapped("name")))
                )
            if template.company_id and companies - template.company_id:
                raise ValidationError(
                    _("Una promoción de %s solo puede aplicarse en esa sucursal.", template.company_id.name)
                )

    @api.depends("promotion_date_start", "promotion_date_end")
    def _compute_promotion_use_dates(self):
        """Marcado si la promoción ya tiene alguna fecha (promociones previas al campo)."""
        for template in self:
            template.promotion_use_dates = bool(template.promotion_date_start or template.promotion_date_end)

    @api.onchange("promotion_use_dates")
    def _onchange_promotion_use_dates(self):
        """Al desmarcar la vigencia se borran las fechas: si no, seguirían aplicando ocultas."""
        if not self.promotion_use_dates:
            self.promotion_date_start = self.promotion_date_end = False

    def write(self, vals):
        """Mismo criterio que el onchange para escrituras que no pasan por el formulario."""
        if "promotion_use_dates" in vals and not vals["promotion_use_dates"]:
            vals = dict(vals, promotion_date_start=False, promotion_date_end=False)
        return super().write(vals)

    @api.constrains("promotion_date_start", "promotion_date_end")
    def _check_promotion_dates(self):
        """La fecha de fin no puede ser anterior a la de inicio."""
        for template in self:
            start, end = template.promotion_date_start, template.promotion_date_end
            if start and end and end < start:
                raise ValidationError(_("La fecha Válida hasta no puede ser anterior a Válida desde."))

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
                if not vals.get("promotion_company_ids"):
                    company = self.env["res.company"].browse(vals.get("company_id"))
                    vals["promotion_company_ids"] = [
                        Command.set(self._promotion_default_companies(company or None).ids)
                    ]
        return super().create(vals_list)
