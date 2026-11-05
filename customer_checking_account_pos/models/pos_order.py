# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, format_amount

_logger = logging.getLogger(__name__)

CCA_STATES = ("paid", "done", "invoiced")


class PosOrder(models.Model):
    _inherit = "pos.order"

    cca_financing_set = fields.Boolean(
        string="Financiación elegida en el POS",
        help="El cajero eligió la financiación en el POS. Si no, se usan los valores de la compañía.",
    )
    cca_surcharge_percent = fields.Float(
        string="Recargo (%)", digits=(5, 2),
        help="Recargo de financiación elegido en el POS para la parte a cuenta corriente.",
    )
    cca_installment_count = fields.Integer(
        string="Cuotas",
        help="Cuotas elegidas en el POS.",
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
        if cc_payments and currency.compare_amounts(
            sum(cc_payments.mapped("amount")), self.amount_total
        ) > 0:
            raise UserError(_(
                "El monto a cuenta corriente no puede superar el total del pedido."
            ))
        if cc_payments and any(
            currency.compare_amounts(line.price_subtotal_incl, 0.0) < 0 for line in self.lines
        ):
            raise UserError(_(
                "Una venta a cuenta corriente no puede tener líneas negativas: "
                "quitá los descuentos en línea o cobrá esa parte con otro medio."
            ))
        return True

    def _cca_financing_values(self, order_date):
        """Financiación elegida en el POS o, si no la hay, la de la compañía (siempre saneada)."""
        self.ensure_one()
        company = self.company_id
        default_due = order_date + timedelta(days=max(company.cca_pos_first_due_days, 0))
        default_frequency = company.cca_pos_frequency or "monthly"
        if self.cca_financing_set:
            return {
                "surcharge_percent": max(self.cca_surcharge_percent, 0.0),
                "installment_count": max(self.cca_installment_count, 1),
                "first_due_date": self.cca_first_due_date or default_due,
                "frequency": self.cca_frequency or default_frequency,
            }
        return {
            "surcharge_percent": max(company.cca_pos_surcharge_percent, 0.0),
            "installment_count": max(company.cca_pos_installment_count, 1),
            "first_due_date": default_due,
            "frequency": default_frequency,
        }

    def _cca_down_payment_method(self):
        """Medio de la entrega o del cobro: efectivo si el medio no-cc de mayor monto cuenta efectivo."""
        self.ensure_one()
        others = self.payment_ids.filtered(
            lambda p: not p.payment_method_id.cca_is_checking_account and not p.is_change
        )
        if not others:
            return "cash"
        main = max(others, key=lambda p: p.amount)
        return "cash" if main.payment_method_id.is_cash_count else "other"

    def _cca_withdrawal_line_values(self):
        """Líneas del retiro con el precio final del ticket (impuestos y descuentos incluidos).

        Si cantidad x precio unitario no reproduce el subtotal del ticket por redondeo, la línea
        va como 1 unidad por el subtotal y la cantidad queda en la descripción.
        """
        self.ensure_one()
        currency = self.currency_id
        price_digits = self.env["decimal.precision"].precision_get("Product Price")
        commands = []
        for line in self.lines.filtered("qty"):
            name = line.full_product_name or line.product_id.display_name
            price_unit = round(line.price_subtotal_incl / line.qty, price_digits)
            quantity = line.qty
            if currency.compare_amounts(
                currency.round(quantity * price_unit), currency.round(line.price_subtotal_incl)
            ):
                name = f"{line.qty:g} x {name}"
                quantity, price_unit = 1.0, line.price_subtotal_incl
            commands.append(fields.Command.create({
                "product_id": line.product_id.id,
                "name": name,
                "quantity": quantity,
                "price_unit": price_unit,
            }))
        return commands

    def _cca_create_withdrawal(self):
        """Crea y confirma el retiro de la parte pagada a cuenta corriente."""
        self.ensure_one()
        currency = self.currency_id
        cc_amount = sum(self._cca_cc_payments().mapped("amount"))
        down_payment = currency.round(self.amount_total - cc_amount)
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
        """Cobro de cuotas: crea el pago por el producto de pago; el create del base lo imputa FIFO."""
        self.ensure_one()
        currency = self.currency_id
        amount = currency.round(sum(self._cca_payment_product_lines().mapped("price_subtotal_incl")))
        payment = self.env["cca.payment"].sudo().with_company(self.company_id).create({
            "partner_id": self.partner_id.id,
            "company_id": self.company_id.id,
            "date": fields.Date.context_today(self, timestamp=self.date_order),
            "amount": amount,
            "payment_method": self._cca_down_payment_method(),
            "ref": self.pos_reference,
            "pos_order_id": self.id,
        })
        self.write({
            "cca_payment_id": payment.id,
            "cca_receipt_info": _(
                "Pago %(name)s · Saldo: %(balance)s",
                name=payment.name,
                balance=format_amount(self.env, payment.account_id.balance, currency),
            ),
        })
        _logger.info("Pedido POS %s: pago %s registrado", self.name, payment.name)
        return payment

    def _cca_process_refund(self):
        """Reembolso: anula el retiro o el pago de cuenta corriente del pedido original.

        Nunca crea retiro ni pago. Un retiro o pago ya anulado se saltea, así el reembolso
        reprocesado no falla. Todo error es UserError para que el sync deshaga el reembolso.
        """
        self.ensure_one()
        original = self.lines.mapped("refunded_orderline_id.order_id")
        if len(original) > 1:
            raise UserError(_("Un reembolso solo puede devolver productos de un mismo pedido."))
        withdrawal = original.cca_withdrawal_id.sudo()
        if withdrawal and not withdrawal.is_cancelled:
            self._cca_check_full_refund(original)
            self._cca_check_refund_payments(original)
            withdrawal.with_context(cca_pos_refund=True).action_cancel()
            _logger.info("Reembolso POS %s: retiro %s cancelado", self.name, withdrawal.name)
        payment = original.cca_payment_id.sudo()
        if payment and payment.state != "cancel":
            payment.action_cancel()
            _logger.info("Reembolso POS %s: pago %s anulado", self.name, payment.name)
        return True

    def _cca_check_full_refund(self, original):
        """Exige que el reembolso devuelva cada línea del pedido original por su cantidad completa."""
        self.ensure_one()
        digits = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        for line in original.lines.filtered("qty"):
            refunded = -sum(self.lines.filtered(lambda r: r.refunded_orderline_id == line).mapped("qty"))
            if float_compare(refunded, line.qty, precision_digits=digits):
                raise UserError(_(
                    "Reembolso parcial de una venta a cuenta corriente: resolvelo desde el backend."
                ))
        return True

    def _cca_check_refund_payments(self, original):
        """Exige que el reembolso devuelva por cada medio lo mismo que se cobró en el original.

        Se compara el neto por medio (el vuelto resta del efectivo): es lo que el retiro tomó
        como entrega y lo que se financió.
        """
        self.ensure_one()
        currency = original.currency_id

        def net_by_method(order):
            """Neto pagado por medio de pago del pedido."""
            totals = {}
            for payment in order.payment_ids:
                method = payment.payment_method_id
                totals[method] = totals.get(method, 0.0) + payment.amount
            return totals

        paid, refunded = net_by_method(original), net_by_method(self)
        for method in set(paid) | set(refunded):
            if currency.compare_amounts(abs(paid.get(method, 0.0)), abs(refunded.get(method, 0.0))):
                raise UserError(_(
                    "El reembolso de una venta a cuenta corriente debe devolverse con los mismos "
                    "medios y montos del pedido %(order)s: lo financiado con %(cc)s y la entrega "
                    "con su medio original.",
                    order=original.pos_reference or original.name,
                    cc=", ".join(original._cca_cc_payments().payment_method_id.mapped("name")),
                ))
        return True
