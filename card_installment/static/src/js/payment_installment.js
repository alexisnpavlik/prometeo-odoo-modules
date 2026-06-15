/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { InfoPopup } from "@card_installment/overrides/components/popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    },

    /**
     * Total neto de la orden (sin recargo de cuotas), tolerante a que el recargo
     * ya esté aplicado: en ese caso restaura temporalmente los precios originales
     * para leer el neto y vuelve a dejar los precios como estaban.
     */
    _getInstallmentNetTotal(order) {
        const lines = order.get_orderlines();
        const modified = lines.filter((l) => l.original_unit_price !== undefined);
        if (modified.length === 0) {
            return order.get_total_with_tax();
        }
        const saved = modified.map((l) => [l, l.get_unit_price()]);
        modified.forEach((l) => l.set_unit_price(l.original_unit_price));
        const net = order.get_total_with_tax();
        saved.forEach(([l, price]) => l.set_unit_price(price));
        return net;
    },

    async onClickInstallments() {
        let paymentline =
            this.currentOrder?.get_selected_paymentline?.() ||
            this.currentOrder?.selected_paymentline;

        if (!paymentline) {
            this.notification.add(_t("Seleccione una línea de pago primero."), { type: "warning" });
            return;
        }

        // Si la línea seleccionada es la de recargo, redirigir a la línea de pago base
        if (paymentline.is_installment) {
            const baseLine = (this.currentOrder?.payment_ids || []).find(
                (pl) =>
                    pl.payment_method_id?.id === paymentline.payment_method_id?.id &&
                    !pl.is_installment
            );
            if (baseLine) {
                paymentline = baseLine;
            }
        }

        const paymentMethod = paymentline.payment_method_id;
        if (!paymentMethod || !paymentMethod.card_id) {
            this.notification.add(_t("Esta línea de pago no tiene tarjeta asociada."), {
                type: "warning",
            });
            return;
        }

        const order = this.env.services.pos.get_order();
        const net_total = this._getInstallmentNetTotal(order);

        const installments = await this.env.services.pos.getInstallments(
            paymentMethod.card_id,
            net_total
        );
        const cardData = installments[paymentMethod.card_id];

        await makeAwaitable(this.dialog, InfoPopup, {
            order: order,
            paymentline: paymentline,
            installments: cardData ? cardData.installments : [],
            getPayload: () => {},
        });
    },

    async addNewPaymentLine(paymentMethod) {
        const card_id = await this.env.services.pos.getCardID(paymentMethod.id);

        // Bloquear si ya existe un pago con tarjeta de crédito
        if (card_id.card_id !== false) {
            const order = this.env.services.pos.get_order();
            const existingCardLine = (order.payment_ids || []).find(
                (pl) => pl.payment_method_id?.card_id
            );
            if (existingCardLine) {
                this.notification.add(
                    _t(
                        "Ya existe un pago con tarjeta de crédito. Eliminá el pago anterior antes de agregar otra tarjeta."
                    ),
                    { type: "warning" }
                );
                return;
            }
            paymentMethod.card_id = card_id.card_id;
        }

        await super.addNewPaymentLine(paymentMethod);
    },

    get isInstallmentsButtonDisabled() {
        const paymentline =
            this.currentOrder?.get_selected_paymentline() ||
            this.currentOrder?.selected_paymentline;
        if (!paymentline || !paymentline.payment_method_id) {
            return true;
        }
        const card_id = paymentline.payment_method_id.card_id;
        return card_id === false || card_id === undefined || card_id === null;
    },

    get selectedInstallmentQty() {
        const paymentline =
            this.currentOrder?.get_selected_paymentline() ||
            this.currentOrder?.selected_paymentline;
        if (!paymentline || !paymentline.payment_method_id) {
            return null;
        }
        let baseLine = paymentline;
        if (paymentline.is_installment) {
            baseLine = (this.currentOrder?.payment_ids || []).find(
                (pl) =>
                    pl.payment_method_id?.id === paymentline.payment_method_id?.id &&
                    !pl.is_installment
            );
        }
        return baseLine ? baseLine.selected_installment_qty : null;
    },

    get currentOrderPaymentReference() {
        return this.currentOrder?.payment_reference || "";
    },

    onPaymentReferenceInput(event) {
        if (this.currentOrder) {
            this.currentOrder.payment_reference = event.target.value;
        }
    },
});
