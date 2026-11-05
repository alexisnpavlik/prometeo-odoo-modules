/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";
import { ask, makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { CcaFinancingPopup } from "@customer_checking_account_pos/js/financing_popup";
import { fetchCcaPartnerSummary } from "@customer_checking_account_pos/js/partner_summary";

patch(PaymentScreen.prototype, {
    /** Al agregar el medio de cuenta corriente abre el popup de financiación. */
    async addNewPaymentLine(paymentMethod) {
        if (!paymentMethod.cca_is_checking_account) {
            return super.addNewPaymentLine(...arguments);
        }
        // Camino propio: el super avisa "generá una factura" para los medios pay_later,
        // que no aplica a la cuenta corriente (el seguimiento lo hace el retiro).
        const line = this.currentOrder.add_paymentline(paymentMethod);
        if (!this.check_cash_rounding_has_been_well_applied()) {
            return;
        }
        if (!line) {
            this.dialog.add(AlertDialog, {
                title: _t("Error"),
                body: _t("There is already an electronic payment in progress."),
            });
            return false;
        }
        this.numberBuffer.reset();
        const order = this.currentOrder;
        if (order.getHasRefundLines() || order.get_total_with_tax() <= 0) {
            // En un reembolso no hay nada que financiar: el servidor anula el retiro original.
            return true;
        }
        return await this.openCcaFinancing(line);
    },

    /** Valores iniciales del popup: los ya elegidos en el pedido o los de la compañía. */
    getCcaFinancingDefaults(order) {
        const company = this.pos.company;
        if (order.cca_financing_set) {
            return {
                surcharge_percent: order.cca_surcharge_percent || 0,
                installment_count: order.cca_installment_count || 1,
                first_due_date: order.cca_first_due_date,
                frequency: order.cca_frequency || "monthly",
            };
        }
        return {
            surcharge_percent: company.cca_pos_surcharge_percent || 0,
            installment_count: Math.max(company.cca_pos_installment_count || 1, 1),
            first_due_date: luxon.DateTime.now()
                .plus({ days: Math.max(company.cca_pos_first_due_days || 0, 0) })
                .toISODate(),
            frequency: company.cca_pos_frequency || "monthly",
        };
    },

    /** Popup de financiación para una línea CC; cancelar quita la línea de pago. */
    async openCcaFinancing(line) {
        const order = this.currentOrder;
        const otherCc = order
            .getCcaPaymentLines()
            .filter((p) => p !== line)
            .reduce((sum, p) => sum + p.get_amount(), 0);
        const maxAmount = roundCurrency(order.get_total_with_tax() - otherCc, order.currency);
        const payload = await makeAwaitable(this.dialog, CcaFinancingPopup, {
            order,
            amount: Math.min(line.get_amount(), maxAmount),
            maxAmount,
            defaults: this.getCcaFinancingDefaults(order),
        });
        if (!payload) {
            this.deletePaymentLine(line.uuid);
            return false;
        }
        line.set_amount(payload.amount);
        Object.assign(order, {
            cca_financing_set: true,
            cca_surcharge_percent: payload.surcharge_percent,
            cca_installment_count: payload.installment_count,
            cca_first_due_date: payload.first_due_date,
            cca_frequency: payload.frequency,
        });
        return true;
    },

    /** Anticipa las reglas del servidor y el límite de crédito antes de validar. */
    async validateOrder(isForceValidate) {
        this.numberBuffer.capture();
        const order = this.currentOrder;
        const error = order.getCcaValidationError();
        if (error) {
            this.dialog.add(AlertDialog, { title: _t("Cuenta corriente"), body: error });
            return;
        }
        if (
            order.getCcaPaymentLines().length &&
            !order.getHasRefundLines() &&
            !(await this.checkCcaCreditLimit(order))
        ) {
            return;
        }
        return super.validateOrder(...arguments);
    },

    /** Saldo + total + recargo contra el límite (igual que el retiro). True si se puede seguir. */
    async checkCcaCreditLimit(order) {
        const summary = await fetchCcaPartnerSummary(this.pos, order.get_partner());
        if (
            !summary?.has_account ||
            summary.limit_mode === "none" ||
            !summary.credit_limit
        ) {
            return true;
        }
        const percent = order.cca_financing_set
            ? order.cca_surcharge_percent
            : this.pos.company.cca_pos_surcharge_percent;
        const surcharge = order.getCcaSurcharge(order.getCcaAmount(), percent);
        const projected = roundCurrency(
            summary.balance + order.get_total_with_tax() + surcharge,
            order.currency
        );
        if (roundCurrency(projected - summary.credit_limit, order.currency) <= 0) {
            return true;
        }
        const fmt = (value) => this.env.utils.formatCurrency(value);
        const message = _t(
            "La venta deja a %(partner)s con un saldo de %(projected)s, por encima de su límite de %(limit)s.",
            {
                partner: order.get_partner().name,
                projected: fmt(projected),
                limit: fmt(summary.credit_limit),
            }
        );
        if (summary.limit_mode === "block") {
            this.dialog.add(AlertDialog, {
                title: _t("Límite de crédito superado"),
                body: _t("%s\n\nSubí el límite en la cuenta del cliente para poder vender.", message),
            });
            return false;
        }
        return await ask(this.dialog, {
            title: _t("Límite de crédito superado"),
            body: _t("%s\n\n¿Seguir con la venta igual?", message),
            confirmLabel: _t("Seguir"),
            cancelLabel: _t("Volver"),
        });
    },
});
