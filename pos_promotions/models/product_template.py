# -*- coding: utf-8 -*-

from datetime import date

from markupsafe import escape

from odoo import Command, _, api, fields, models, tools
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date



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
    promotion_use_dates = fields.Boolean(
        "Tiene vigencia", compute="_compute_promotion_use_dates", store=True, readonly=False,
        help="Marcalo para cargar desde y hasta cuándo vale. Sin marcar, vale siempre mientras esté activa.",
    )
    promotion_branch_prices_html = fields.Html(
        "Precio en cada sucursal", compute="_compute_promotion_branch_prices_html", sanitize=False,
    )
    promotion_branch_rule_count = fields.Integer(compute="_compute_promotion_branch_prices_html")
    promotion_expired = fields.Boolean("Vencida", compute="_compute_promotion_expired")
    promotion_status = fields.Selection(
        [("active", "Vigente"), ("scheduled", "Programada"), ("expired", "Vencida")],
        string="Estado", compute="_compute_promotion_expired",
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
        help="Sucursales que se pueden elegir: todas a las que el usuario tiene acceso, o solo la de la promoción.",
    )

    @api.model
    def _promotion_allowed_companies(self):
        """Sucursales que puede usar una promoción: todas las empresas."""
        return self.env["res.company"].sudo().search([])

    @api.model
    def _promotion_default_companies(self, company=None):
        """Sucursales que trae una promoción nueva: todas a las que el usuario tiene acceso,
        estén o no activas en el selector; si la promoción tiene empresa, solo esa."""
        companies = self._promotion_allowed_companies() & self.env.user.company_ids
        return companies & company if company else companies

    @api.depends("company_id")
    @api.depends_context("uid")
    def _compute_promotion_allowed_company_ids(self):
        """Opciones del campo Sucursales: las que el usuario tiene acceso (el formulario
        muestra sus nombres); con empresa en la promoción, solo esa."""
        allowed = self._promotion_allowed_companies() & self.env.user.company_ids
        for template in self:
            options = allowed & template.company_id if template.company_id else allowed
            template.promotion_allowed_company_ids = [Command.set(options.ids)]

    @api.model
    def default_get(self, fields_list):
        """Una promoción nueva arranca con todas las sucursales seleccionadas."""
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
        en el default de Odoo (1) o en la última suma sugerida; un precio puesto a mano se respeta."""
        for template in self.filtered("is_promotion_pack"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            if template.promotion_price_mode == "percent":
                # Precio de referencia que muestra la tarjeta del POS; el real sale de la lista.
                if regular:
                    template.list_price = round(regular * (1 - template.promotion_discount_percent / 100), 2)
                continue
            price = template.list_price
            if regular and (price <= 1 or price == template.promotion_pack_auto_price):
                template.list_price = template.promotion_pack_auto_price = regular

    @api.constrains("is_promotion_pack", "list_price", "promotion_pack_line_ids", "promotion_price_mode",
                    "promotion_discount_percent")
    def _check_promotion_pack_price(self):
        """Precio fijo: más de 1. %: entre 0 y 100."""
        for template in self.filtered("is_promotion_pack"):
            if template.promotion_price_mode == "percent":
                if not 0 < template.promotion_discount_percent < 100:
                    raise ValidationError(_("El descuento tiene que ser mayor a 0 y menor a 100%."))
                continue
            # Sin tope contra los sueltos: hay combos que cuestan más juntos (en el POS sube el precio).
            if template.list_price <= 1:
                raise ValidationError(_("Poné el precio de la promoción (no puede ser 1 o menos)."))

    @api.constrains("is_promotion_pack", "promotion_company_ids", "company_id")
    def _check_promotion_companies(self):
        """Al menos una sucursal; si la promoción tiene empresa, solo esa."""
        for template in self.filtered("is_promotion_pack"):
            companies = template.sudo().promotion_company_ids
            if not companies:
                raise ValidationError(_("Elegí al menos una sucursal para la promoción."))
            if template.company_id and companies - template.company_id:
                raise ValidationError(
                    _("Una promoción de %s solo puede aplicarse en esa sucursal.", template.company_id.name)
                )

    @api.depends("promotion_date_start", "promotion_date_end")
    def _compute_promotion_use_dates(self):
        """Marcado si la promoción ya tiene alguna fecha (promociones previas al campo)."""
        for template in self:
            template.promotion_use_dates = bool(template.promotion_date_start or template.promotion_date_end)

    @api.depends("promotion_company_ids", "promotion_pack_line_ids.product_id", "promotion_pack_line_ids.quantity",
                 "promotion_price_mode", "promotion_discount_percent", "list_price")
    def _compute_promotion_branch_prices_html(self):
        """Tabla de lo que cobra la caja en cada sucursal elegida: la lista de sus cajas, los
        productos sueltos a ese precio y la promoción. Marca las listas con precio propio
        para alguno de los productos (regla por producto, no una regla general)."""
        configs = self.env["pos.config"].sudo().search([("pricelist_id", "!=", False)])
        for template in self:
            lines = template.promotion_pack_line_ids.filtered("product_id")
            rows, rule_count = [], 0
            for company in template.promotion_company_ids.sudo():
                for pricelist in configs.filtered(lambda c: c.company_id == company).pricelist_id:
                    regular, ruled = 0.0, []
                    for line in lines:
                        product = line.product_id.sudo()
                        regular += pricelist._get_product_price(product, line.quantity) * line.quantity
                        rule = self.env["product.pricelist.item"].sudo().browse(
                            pricelist._get_product_rule(product, line.quantity)
                        )
                        if rule and rule.applied_on in ("0_product_variant", "1_product"):
                            ruled.append(product.name)
                    if template.promotion_price_mode == "percent":
                        promo = regular * (1 - template.promotion_discount_percent / 100)
                    else:
                        promo = template.list_price
                    rule_count += bool(ruled)
                    rows.append((company.name, pricelist.name, regular, promo, ruled))
            template.promotion_branch_rule_count = rule_count
            if not rows or not lines:
                template.promotion_branch_prices_html = False
                continue
            currency = template.currency_id
            fmt = lambda amount: tools.format_amount(self.env, amount, currency)
            body = []
            for company_name, pricelist_name, regular, promo, ruled in rows:
                diff = promo - regular
                diff_cls = "text-success" if diff < 0 else "text-danger" if diff > 0 else ""
                note = (_("Precio propio en la lista: %s", ", ".join(ruled)) if ruled else "")
                body.append(
                    f'<tr class="{"table-warning" if ruled else ""}">'
                    f"<td>{escape(company_name)}</td><td>{escape(pricelist_name)}</td>"
                    f'<td class="text-end">{fmt(regular)}</td><td class="text-end">{fmt(promo)}</td>'
                    f'<td class="text-end {diff_cls}">{fmt(diff)}</td><td>{escape(note)}</td></tr>'
                )
            template.promotion_branch_prices_html = (
                '<table class="table table-sm o_promotion_branch_prices"><thead><tr>'
                f'<th>{_("Sucursal")}</th><th>{_("Lista de la caja")}</th>'
                f'<th class="text-end">{_("Sueltos")}</th><th class="text-end">{_("Promoción")}</th>'
                f'<th class="text-end">{_("Diferencia")}</th><th></th></tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table>'
            )

    @api.depends("promotion_date_start", "promotion_date_end")
    @api.depends_context("tz")
    def _compute_promotion_expired(self):
        """Vencida si Válida hasta ya pasó (el último día todavía vale); Programada si
        todavía no llegó Válida desde."""
        today = fields.Date.context_today(self)
        for template in self:
            start, end = template.promotion_date_start, template.promotion_date_end
            template.promotion_expired = bool(end and end < today)
            if template.promotion_expired:
                template.promotion_status = "expired"
            elif start and start > today:
                template.promotion_status = "scheduled"
            else:
                template.promotion_status = "active"

    @api.onchange("promotion_use_dates")
    def _onchange_promotion_use_dates(self):
        """Al desmarcar la vigencia se borran las fechas: si no, seguirían aplicando ocultas."""
        if not self.promotion_use_dates:
            self.promotion_date_start = self.promotion_date_end = False

    def write(self, vals):
        """Mismo criterio que los onchange para escrituras que no pasan por el formulario."""
        if "promotion_use_dates" in vals and not vals["promotion_use_dates"]:
            vals = dict(vals, promotion_date_start=False, promotion_date_end=False)
        res = super().write(vals)
        if {"promotion_price_mode", "promotion_discount_percent", "promotion_pack_line_ids"} & set(vals):
            self._promotion_sync_percent_price()
        return res

    def _promotion_sync_percent_price(self):
        """Con % de descuento, el precio de la ficha (el que muestra la tarjeta del POS) es
        el de los sueltos con el descuento; la caja cobra sobre la lista de la sucursal."""
        for template in self.filtered(lambda t: t.is_promotion_pack and t.promotion_price_mode == "percent"):
            regular = sum(line.lst_price * line.quantity for line in template.promotion_pack_line_ids)
            price = round(regular * (1 - template.promotion_discount_percent / 100), 2)
            if regular and template.list_price != price:
                super(ProductTemplate, template).write({"list_price": price})

    def _promotion_signature(self):
        """Productos y cantidades de la promoción, sin importar el orden de las líneas."""
        totals = {}
        for line in self.sudo().promotion_pack_line_ids:
            totals[line.product_id.id] = totals.get(line.product_id.id, 0) + line.quantity
        return tuple(sorted(totals.items()))

    @api.constrains("is_promotion_pack", "active", "promotion_pack_line_ids", "promotion_company_ids",
                    "promotion_date_start", "promotion_date_end")
    def _check_promotion_duplicates(self):
        """Dos promociones activas con los mismos productos, alguna sucursal en común y
        fechas que se superponen chocan: en la caja solo se aplicaría la que más ahorra.
        Sin fechas cuenta como siempre."""
        for template in self.filtered(lambda t: t.is_promotion_pack and t.active and t.promotion_pack_line_ids):
            signature = template._promotion_signature()
            start = template.promotion_date_start or date.min
            end = template.promotion_date_end or date.max
            candidates = self.sudo().search([
                ("is_promotion_pack", "=", True),
                ("id", "!=", template.id),
                ("promotion_pack_line_ids.product_id", "=", signature[0][0]),
                ("promotion_company_ids", "in", template.sudo().promotion_company_ids.ids),
            ])
            for other in candidates:
                other_start = other.promotion_date_start or date.min
                other_end = other.promotion_date_end or date.max
                if other_start > end or start > other_end or other._promotion_signature() != signature:
                    continue
                shared = other.promotion_company_ids & template.sudo().promotion_company_ids
                if other.promotion_date_start or other.promotion_date_end:
                    period = _("entre %(start)s y %(end)s",
                               start=format_date(self.env, other.promotion_date_start) if other.promotion_date_start else _("siempre"),
                               end=format_date(self.env, other.promotion_date_end) if other.promotion_date_end else _("sin vencimiento"))
                else:
                    period = _("sin fechas (vale siempre)")
                raise ValidationError(_(
                    "Ya existe '%(other)s' con los mismos productos en %(companies)s, %(period)s. "
                    "Desactivala o cambiá las fechas o las sucursales.",
                    other=other.name, companies=", ".join(shared.mapped("name")), period=period,
                ))

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
        templates = super().create(vals_list)
        templates._promotion_sync_percent_price()
        return templates
