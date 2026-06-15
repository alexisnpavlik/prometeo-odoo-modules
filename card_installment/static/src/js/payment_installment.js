/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { InfoPopup } from "@card_installment/overrides/components/popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { _t } from "@web/core/l10n/translation";
import { onWillUnmount } from "@odoo/owl";
import { calculateInstallmentValues } from "@card_installment/js/installment_math";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
        onWillUnmount(() => {
            if (this.currentOrder && !this.currentOrder.finalized) {
                const installmentLine = (this.currentOrder.payment_ids || []).find(pl => pl.is_installment);
                if (installmentLine) {
                    this.currentOrder.remove_paymentline(installmentLine);
                }
            }
        });
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

        // Fetch installments from cache first (fully offline-compatible)
        let cardInstallments = [];
        const posStore = this.pos || this.env.services.pos;
        const models = posStore.models || posStore.data?.models;
        if (models && models["account.card.installment"]) {
            const all = models["account.card.installment"].getAll() || [];
            cardInstallments = all.filter(
                (inst) => inst.active && (Array.isArray(inst.card_id) ? inst.card_id[0] : inst.card_id) === paymentMethod.card_id
            ).map(inst => calculateInstallmentValues(inst, net_total));
        }

        // Fallback to RPC if local cache is empty / not loaded
        if (cardInstallments.length === 0) {
            try {
                const installments = await this.env.services.pos.getInstallments(
                    paymentMethod.card_id,
                    net_total
                );
                const cardData = installments[paymentMethod.card_id];
                cardInstallments = cardData ? cardData.installments : [];
            } catch (err) {
                console.error("Error fetching installments via RPC:", err);
                this.notification.add(
                    _t("Error al conectar con el servidor para obtener las cuotas."),
                    { type: "danger" }
                );
                return;
            }
        }

        await makeAwaitable(this.dialog, InfoPopup, {
            order: order,
            paymentline: paymentline,
            installments: cardInstallments,
            getPayload: () => {},
        });
    },

    async addNewPaymentLine(paymentMethod) {
        // En Odoo 18, card_id ya viene precargado en el frontend en el modelo pos.payment.method.
        // No es necesario realizar la llamada getCardID mediante RPC.
        const card_id = paymentMethod.card_id;

        // Bloquear si ya existe un pago con tarjeta de crédito
        if (card_id) {
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
