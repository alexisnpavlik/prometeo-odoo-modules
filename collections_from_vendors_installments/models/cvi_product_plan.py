# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

FREQUENCY_SELECTION = [
    ("monthly", "Mensual"),
    ("weekly", "Semanal"),
]


class CviProductPlan(models.Model):
    _name = "cvi.product.plan"
    _description = "Plan de cuotas de un modelo de mueble"
    _order = "product_tmpl_id, sequence, installment_count"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Modelo de mueble",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Orden", default=10)
    name = fields.Char(
        string="Plan",
        required=True,
        help="Cómo lo nombra el vendedor en la calle: '12 cuotas', '20 semanas'.",
    )
    active = fields.Boolean(
        string="Activo",
        default=True,
        help="Un plan archivado deja de ofrecerse en ventas nuevas, "
             "pero las tarjetas ya vendidas con él no se tocan.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id", string="Moneda", readonly=True
    )
    installment_count = fields.Integer(string="Cantidad de cuotas", required=True)
    installment_amount = fields.Monetary(
        string="Importe de cuota", required=True, currency_field="currency_id"
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION,
        string="Frecuencia",
        default="monthly",
        required=True,
    )
    amount_total = fields.Monetary(
        string="Precio total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        help="Cantidad de cuotas por importe de cuota. El recargo por financiación "
             "ya está incluido en el importe de cada plan.",
    )

    _sql_constraints = [
        (
            "name_unique_per_product",
            "UNIQUE(product_tmpl_id, name)",
            "Ese modelo de mueble ya tiene un plan con ese nombre.",
        ),
    ]

    @api.depends("installment_count", "installment_amount")
    def _compute_amount_total(self):
        """El total de un plan es siempre cuotas por importe: nunca se carga a mano."""
        for plan in self:
            plan.amount_total = plan.installment_count * plan.installment_amount

    @api.constrains("installment_count", "installment_amount")
    def _check_plan_values(self):
        """Un plan sin cuotas o con cuota de importe cero no es vendible."""
        for plan in self:
            if plan.installment_count < 1:
                raise ValidationError(_(
                    "El plan %s debe tener al menos una cuota.", plan.name
                ))
            if plan.installment_amount <= 0:
                raise ValidationError(_(
                    "El importe de cuota del plan %s debe ser mayor a cero.", plan.name
                ))

    @api.depends("name", "installment_count", "installment_amount", "currency_id")
    def _compute_display_name(self):
        """Se muestra con el importe, para que el vendedor elija de un vistazo."""
        for plan in self:
            amount = plan.currency_id.format(plan.installment_amount)
            plan.display_name = _(
                "%(name)s de %(amount)s", name=plan.name, amount=amount
            )
