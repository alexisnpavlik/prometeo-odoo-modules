# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_amount

_logger = logging.getLogger(__name__)

CCA_STATES = ("paid", "done", "invoiced")


class PosOrder(models.Model):
    _inherit = "pos.order"

    cca_surcharge_percent = fields.Float(
        string="Recargo (%)", digits=(5, 2),
        help="Recargo de financiación elegido en el POS para la parte a cuenta corriente.",
    )
    cca_installment_count = fields.Integer(
        string="Cuotas",
        help="Cuotas elegidas en el POS. Vacío: se usan los valores de la compañía.",
    )
    cca_first_due_date = fields.Date(string="Primer vencimiento")
    cca_frequency = fields.Selection(
        selection=[("monthly", "Mensual"), ("weekly", "Semanal")],
        string="Frecuencia",
    )
    cca_withdrawal_id = fields.Many2one(
        "cca.withdrawal", string="Retiro de cuenta corriente", readonly=True, copy=False, index=True,
    )
    cca_payment_id = fields.Many2one(
        "cca.payment", string="Pago de cuenta corriente", readonly=True, copy=False, index=True,
    )
    cca_receipt_info = fields.Char(
        string="Línea del ticket", readonly=True, copy=False,
        help="Texto de cuenta corriente que imprime el ticket del POS.",
    )

    @api.model
    def _process_order(self, order, existing_order):
        """Después de guardar el pedido pagado, genera el movimiento de cuenta corriente.

        Corre en la misma transacción del sync: un UserError deshace también el pedido.
        """
        order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(order_id)
        if pos_order.state in CCA_STATES:
            pos_order._cca_process()
        return order_id

    def _cca_cc_payments(self):
        """Pagos del pedido hechos con el método de cuenta corriente."""
        self.ensure_one()
        return self.payment_ids.filtered(lambda p: p.payment_method_id.cca_is_checking_account)

    def _cca_payment_product_lines(self):
        """Líneas del producto de pago de cuenta corriente de la caja."""
        self.ensure_one()
        product = self.config_id.cca_payment_product_id
        if not product:
            return self.env["pos.order.line"]
        return self.lines.filtered(lambda line: line.product_id == product)

    def _cca_process(self):
        """Crea el retiro (venta a cuenta) o el pago (cobro de cuotas) del pedido. Idempotente."""
        for order in self:
            if order.cca_withdrawal_id or order.cca_payment_id:
                continue
            if any(order.lines.mapped("refunded_orderline_id")):
                order._cca_process_refund()
                continue
            cc_payments = order._cca_cc_payments()
            payment_lines = order._cca_payment_product_lines()
            if not cc_payments and not payment_lines:
                continue
            order._cca_check_rules()
            if cc_payments:
                order._cca_create_withdrawal()
            if payment_lines:
                order._cca_create_payment()
        return True

    def _cca_check_rules(self):
        """Valida en el servidor las reglas de cuenta corriente que el POS anticipa."""
        self.ensure_one()
        cc_payments = self._cca_cc_payments()
        payment_lines = self._cca_payment_product_lines()
        if not cc_payments and not payment_lines:
            return True
        if not self.partner_id:
            raise UserError(_("Elegí un cliente para operar con cuenta corriente."))
        if not self.partner_id.vat:
            raise UserError(_(
                "Cargá el DNI de %s antes de operar con cuenta corriente.", self.partner_id.display_name
            ))
        if cc_payments and payment_lines:
            raise UserError(_(
                "No se puede vender a cuenta corriente y cobrar cuotas en el mismo pedido."
            ))
        currency = self.currency_id
        if payment_lines and currency.compare_amounts(
            sum(payment_lines.mapped("price_subtotal_incl")), 0.0
        ) <= 0:
            raise UserError(_("El pago de cuenta corriente debe ser mayor a cero."))
        if cc_payments and any(
            currency.compare_amounts(line.price_subtotal_incl, 0.0) < 0 for line in self.lines
        ):
            raise UserError(_(
                "Una venta a cuenta corriente no puede tener líneas negativas: "
                "quitá los descuentos en línea o cobrá esa parte con otro medio."
            ))
        return True

    def _cca_financing_values(self, order_date):
        """Financiación del pedido; si no viene del POS, los valores de la compañía (saneados)."""
        self.ensure_one()
        company = self.company_id
        # Las cuotas marcan si el POS mandó financiación: así un recargo 0 elegido no cae al default.
        from_pos = self.cca_installment_count > 0
        surcharge = self.cca_surcharge_percent if from_pos else company.cca_pos_surcharge_percent
        count = self.cca_installment_count if from_pos else company.cca_pos_installment_count
        return {
            "surcharge_percent": max(surcharge, 0.0),
            "installment_count": max(count, 1),
            "first_due_date": self.cca_first_due_date
            or order_date + timedelta(days=max(company.cca_pos_first_due_days, 0)),
            "frequency": self.cca_frequency or company.cca_pos_frequency or "monthly",
        }

    def _cca_down_payment_method(self):
        """Medio de la entrega: efectivo si el medio no-cc de mayor monto cuenta efectivo."""
        self.ensure_one()
        others = self.payment_ids.filtered(
            lambda p: not p.payment_method_id.cca_is_checking_account and not p.is_change
        )
        if not others:
            return "cash"
        main = max(others, key=lambda p: p.amount)
        return "cash" if main.payment_method_id.is_cash_count else "other"

    def _cca_withdrawal_line_values(self):
        """Líneas del retiro con el precio final del ticket (impuestos y descuentos incluidos)."""
        self.ensure_one()
        return [
            fields.Command.create({
                "product_id": line.product_id.id,
                "name": line.full_product_name or line.product_id.display_name,
                "quantity": line.qty,
                "price_unit": line.price_subtotal_incl / line.qty,
            })
            for line in self.lines
            if line.qty
        ]

    def _cca_create_withdrawal(self):
        """Crea y confirma el retiro de la parte pagada a cuenta corriente."""
        self.ensure_one()
        currency = self.currency_id
        cc_amount = sum(self._cca_cc_payments().mapped("amount"))
        down_payment = currency.round(self.amount_total - cc_amount)
        if currency.compare_amounts(down_payment, 0.0) < 0:
            down_payment = 0.0
        order_date = fields.Date.context_today(self, timestamp=self.date_order)
        vals = {
            "partner_id": self.partner_id.id,
            "company_id": self.company_id.id,
            "date": order_date,
            "pos_order_id": self.id,
            "down_payment": down_payment,
            "down_payment_method": self._cca_down_payment_method(),
            "note": _("Venta del POS %s", self.pos_reference or self.name),
            "line_ids": self._cca_withdrawal_line_values(),
            **self._cca_financing_values(order_date),
        }
        withdrawal = self.env["cca.withdrawal"].sudo().with_company(self.company_id).create(vals)
        withdrawal.action_confirm()
        installments = withdrawal.installment_ids.filtered(lambda i: not i.is_down_payment).sorted("sequence")
        self.write({
            "cca_withdrawal_id": withdrawal.id,
            "cca_receipt_info": _(
                "Cuenta corriente: %(name)s · %(n)s cuota(s) de %(amount)s",
                name=withdrawal.name,
                n=withdrawal.installment_count,
                amount=format_amount(self.env, installments[:1].amount, currency),
            ),
        })
        _logger.info("Pedido POS %s: retiro %s confirmado", self.name, withdrawal.name)
        return withdrawal

    def _cca_create_payment(self):
        """Cobro de cuotas con el producto de pago. Lo implementa la Task 4."""
        return False

    def _cca_process_refund(self):
        """Reembolso de un pedido con cuenta corriente. Lo implementa la Task 5."""
        return False
