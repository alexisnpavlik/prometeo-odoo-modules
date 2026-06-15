##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP


class AccountCardInstallment(models.Model):
    _name = "account.card.installment"
    _description = "amount to add for collection in installments"

    card_id = fields.Many2one(
        "account.card",
        string="Card",
        required=True,
    )
    name = fields.Char("Fantasy Name", default="/", help="Nombre informativo del plan a mostrar")
    divisor = fields.Integer(help="Número por el cual se dividirá el total de cuotas que pagará el usuario final")
    installment = fields.Integer(
        string="Installment Plan",
        help="Plan de cuotas a informar, en caso de utilizar método de pago electrónico: el valor del plan a informar al gateway de pago",
    )
    surcharge_coefficient = fields.Float(
        default=1.0,
        digits="Installment coefficient",
        help="Factor a aplicar sobre el monto total para calcular el cargo financiero. Por ejemplo el formato para el recargo de un 6% se aplica con el valor 1.06.",
    )
    bank_discount = fields.Float(
        help="Porcentaje de reintegro (el reintegro se efectúa sobre el total incluído el recargo financiero) que acuerda el vendedor con el banco o marca de tarjeta para devolución en compra"
    )
    active = fields.Boolean(default=True)

    @api.depends("card_id", "card_id.name", "name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.name} ({record.card_id.name})"

    @api.constrains("divisor")
    def _check_divisor(self):
        for record in self:
            if record.divisor < 1:
                raise ValidationError(_("Divisor must be greater than 0"))

    def card_installment_tree(self, amount_total):
        tree = {}
        for card in self.mapped("card_id"):
            tree[card.id] = card.map_card_values()

        for installment in self:
            tree[installment.card_id.id]["installments"].append(installment.map_installment_values(amount_total))
        return tree

    def map_installment_values(self, amount_total):
        self.ensure_one()

        cents = Decimal("0.01")

        # Coeficiente con la precisión real del campo (5 decimales), no truncado a 2
        coefficient = Decimal(str(self.surcharge_coefficient)).quantize(
            Decimal("0.00001"),
            rounding=ROUND_HALF_UP
        )

        amount_total_d = Decimal(str(amount_total)).quantize(cents, rounding=ROUND_HALF_UP)
        divisor_d = Decimal(str(self.divisor)) if self.divisor else Decimal("0")

        # Total con el recargo financiero aplicado
        amount = (amount_total_d * coefficient).quantize(cents, rounding=ROUND_HALF_UP)

        # Reintegro/descuento: porcentaje sobre el total ya incluído el recargo
        discount_pct = Decimal(str(self.bank_discount or 0))
        discount = (amount * discount_pct / Decimal("100")).quantize(cents, rounding=ROUND_HALF_UP)

        # Total a cobrar realmente (recargo - reintegro)
        final_amount = amount - discount

        # La cuota se calcula sobre lo que efectivamente paga el cliente
        if divisor_d > 0:
            installment_amount_d = (final_amount / divisor_d).quantize(cents, rounding=ROUND_HALF_UP)
        else:
            installment_amount_d = Decimal("0.00")
        installment_amount = float(installment_amount_d)

        return {
            "id": self.id,
            "name": self.name,
            "installment": self.installment,
            "coefficient": float(coefficient),
            "bank_discount": self.bank_discount,
            "divisor": self.divisor,
            "base_amount": float(amount_total_d),    # total neto sin recargo
            "amount": float(amount),                 # total con recargo financiero
            "fee": float(amount - amount_total_d),   # cargo financiero
            "discount": float(discount),             # reintegro aplicado
            "final_amount": float(final_amount),     # total a cobrar (recargo - reintegro)
            "description": _("%s installment of %.2f (total %.2f)")
            % (self.divisor, installment_amount, float(final_amount)),
        }

