# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .cvi_product_plan import FREQUENCY_SELECTION


class CviCardLine(models.Model):
    _name = "cvi.card.line"
    _description = "Mueble vendido en una tarjeta"
    _order = "card_id, sequence, id"

    card_id = fields.Many2one(
        "cvi.card", string="Tarjeta", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(string="Orden", default=10)
    company_id = fields.Many2one(related="card_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="card_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        "product.product",
        string="Modelo de mueble",
        required=True,
        domain="[('is_storable', '=', True)]",
    )
    product_tmpl_id = fields.Many2one(
        related="product_id.product_tmpl_id", string="Ficha del mueble", readonly=True,
    )
    plan_id = fields.Many2one(
        "cvi.product.plan",
        string="Plan de cuotas",
        required=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]",
        help="Los planes se definen en la ficha del mueble, pestaña Planes de cuotas.",
    )
    quantity = fields.Float(string="Cantidad", default=1.0, required=True)
    installment_count = fields.Integer(
        string="Cuotas", compute="_compute_installment_count",
        store=True, readonly=False,
    )
    installment_amount = fields.Monetary(
        string="Importe por cuota",
        compute="_compute_installment_amount", store=True, readonly=False,
        currency_field="currency_id",
        help="Importe unitario del plan. Lo que suma esta línea a cada cuota de la "
             "tarjeta es este importe por la cantidad.",
    )
    frequency = fields.Selection(
        selection=FREQUENCY_SELECTION, string="Frecuencia",
        compute="_compute_frequency", store=True, readonly=False,
    )
    amount_per_installment = fields.Monetary(
        string="Aporte por cuota", compute="_compute_amounts", store=True,
        currency_field="currency_id",
        help="Lo que esta línea suma a cada una de sus cuotas: importe por cantidad.",
    )
    amount_subtotal = fields.Monetary(
        string="Subtotal", compute="_compute_amounts", store=True,
        currency_field="currency_id",
    )

    _sql_constraints = [
        ("quantity_positive", "CHECK(quantity > 0)",
         "La cantidad tiene que ser mayor a cero."),
    ]

    # Los tres computes van separados a propósito, uno por campo. La protección de
    # Odoo contra pisar valores explícitos es a nivel de MÉTODO: con uno solo, pasar
    # installment_amount en el create saltearía también el cálculo de los otros dos y
    # la línea quedaría con cero cuotas. Es el mismo motivo por el que están separados
    # en cvi.card, y se rompió acá al escribir este modelo.
    @api.depends("plan_id")
    def _compute_installment_count(self):
        for line in self:
            line.installment_count = line.plan_id.installment_count

    @api.depends("plan_id")
    def _compute_installment_amount(self):
        for line in self:
            line.installment_amount = line.plan_id.installment_amount

    @api.depends("plan_id")
    def _compute_frequency(self):
        for line in self:
            line.frequency = line.plan_id.frequency or "monthly"

    @api.depends("installment_count", "installment_amount", "quantity")
    def _compute_amounts(self):
        for line in self:
            line.amount_per_installment = line.installment_amount * line.quantity
            line.amount_subtotal = line.amount_per_installment * line.installment_count

    @api.constrains("plan_id", "product_id")
    def _check_plan_belongs_to_product(self):
        """El plan elegido tiene que ser uno de los cargados en la ficha de ese mueble."""
        for line in self:
            if line.plan_id.product_tmpl_id != line.product_id.product_tmpl_id:
                raise ValidationError(_(
                    "El plan %(plan)s pertenece a %(plan_product)s, no a %(product)s.",
                    plan=line.plan_id.name,
                    plan_product=line.plan_id.product_tmpl_id.display_name,
                    product=line.product_id.display_name,
                ))

    @api.constrains("plan_id", "installment_count", "installment_amount", "frequency")
    def _check_plan_values(self):
        """Solo el administrador vende con valores distintos a los del plan (RN-05)."""
        if self.env.user.has_group(
            "collections_from_vendors_installments.group_cvi_manager"
        ):
            return
        for line in self:
            plan = line.plan_id
            currency = line.currency_id
            differs = (
                line.installment_count != plan.installment_count
                or currency.compare_amounts(
                    line.installment_amount, plan.installment_amount
                ) != 0
                or line.frequency != plan.frequency
            )
            if differs:
                raise ValidationError(_(
                    "El plan %(plan)s se vende en %(count)s cuotas de %(amount)s. "
                    "Solo el administrador puede cambiar esos valores.",
                    plan=plan.name,
                    count=plan.installment_count,
                    amount=plan.installment_amount,
                ))

    def _cvi_check_card_open(self, action):
        """Una venta confirmada tiene su mercadería descontada y sus cuotas generadas.

        Tocar las líneas después cambiaría el precio de una venta ya cerrada, que es
        justo lo que prohíbe RN-05.
        """
        locked = self.filtered(
            lambda line: line.card_id.state not in ("draft", "cancel")
        )
        if locked:
            raise UserError(_(
                "No se puede %(action)s mercadería en la tarjeta %(card)s: la venta "
                "ya está confirmada.",
                action=action, card=locked[0].card_id.name,
            ))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._cvi_check_card_open(_("agregar"))
        return lines

    def write(self, vals):
        self._cvi_check_card_open(_("modificar"))
        return super().write(vals)

    def unlink(self):
        self._cvi_check_card_open(_("quitar"))
        return super().unlink()
