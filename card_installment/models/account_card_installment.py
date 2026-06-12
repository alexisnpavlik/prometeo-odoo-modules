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
            if record.divisor < 0:
                raise ValidationError(_("Divisor cannot be negative"))

    def get_fees(self, amount):
        self.ensure_one()
        return amount * self.surcharge_coefficient - amount

    def get_real_total(self, amount):
        self.ensure_one()
        return amount * self.surcharge_coefficient

    def card_installment_tree(self, amount_total):
        tree = {}
        for card in self.mapped("card_id"):
            tree[card.id] = card.map_card_values()

        for installment in self:
            tree[installment.card_id.id]["installments"].append(installment.map_installment_values(amount_total))
        return tree

    def map_installment_values(self, amount_total):
        self.ensure_one()

        # Convertir coeficiente a Decimal
        coefficient = Decimal(str(self.surcharge_coefficient)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # Convertir monto total a Decimal
        amount_total_d = Decimal(str(amount_total)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )

        # Convertir divisor
        divisor_d = Decimal(str(self.divisor)) if self.divisor else Decimal("0")

        # Calcular monto total con el coeficiente
        amount = amount_total_d * coefficient

        # Calcular cuota
        if divisor_d > 0:
            installment_amount_d = (amount / divisor_d).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )
        else:
            installment_amount_d = Decimal("0.00")

        # ¡OJO! Convertir a float SOLO si lo necesitas para mostrar
        installment_amount = float(installment_amount_d)

        return {
            "id": self.id,
            "name": self.name,
            "installment": self.installment,
            "coefficient": float(coefficient),
            "bank_discount": self.bank_discount,
            "divisor": self.divisor,
            "base_amount": float(amount_total_d),    # evitar float original
            "amount": float(amount),                 # convertir Decimal → float
            "fee": float(amount - amount_total_d),   # evitar Decimal - float
            "description": _("%s installment of %.2f (total %.2f)")
            % (self.divisor, installment_amount, float(amount)),
        }

