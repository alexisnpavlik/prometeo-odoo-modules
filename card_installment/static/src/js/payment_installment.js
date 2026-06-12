/** @odoo-module **/

// import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
// import { patch } from "@web/core/utils/patch";
// import { useService } from "@web/core/utils/hooks";

// patch(PaymentScreen.prototype, {
//     setup() {
//         super.setup();
//         this.orm = useService("orm");
//         console.log("✅ Patch de PaymentScreen cargado correctamente");
//     },

//     async addNewPaymentLine(paymentMethod) {
//         console.log("💳 Método de pago seleccionado:", paymentMethod);
//         console.log("💳 card_id recibido:", paymentMethod.card_id);

//         await super.addNewPaymentLine(paymentMethod);

//         if (paymentMethod && paymentMethod.card_id) {
//             try {
//                 const amount_total = this.currentOrder?.get_total_with_tax?.() || 0;

//                 const installments = await this.orm.call(
//                     "account.card.installment",
//                     "card_installment_tree",
//                     [[paymentMethod.card_id], amount_total],
//                 );

//                 console.log("📦 Cuotas recibidas:", installments);
//             } catch (error) {
//                 console.error("Error al obtener cuotas:", error);
//             }
//         }
//     },

//     async print_Something() {
//         console.log("Imprimiendo algo desde el patch de PaymentScreen...");
//     }
// });


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
        console.log("✅ Patch de PaymentScreen cargado correctamente");
    },

    async remove_paymentline(paymentline) {
        console.log("🗑️ Payment line eliminada:", paymentline);
    },

    async onClickInstallments() {
        debugger;
        console.log("👉 Botón de cuotas presionado");

        let paymentline =
            this.currentOrder?.get_selected_paymentline?.() ||
            this.currentOrder?.selected_paymentline;

        console.log("💳 paymentline:", paymentline);

        if (!paymentline) {
            console.warn("⚠️ No hay ninguna línea de pago seleccionada todavía.");
            // Aquí puedes mostrar mensaje, pero por ahora solo log
            return;
        }

        // 🔹 Si la línea seleccionada es la de recargo (is_installment), redirigimos a la línea de pago base
        if (paymentline.is_installment) {
            const baseLine = (this.currentOrder?.payment_ids || []).find(
                (pl) => pl.payment_method_id?.id === paymentline.payment_method_id?.id && !pl.is_installment
            );
            if (baseLine) {
                console.log("💳 Redirigiendo a la línea de pago base seleccionada:", baseLine);
                paymentline = baseLine;
            }
        }

        const paymentMethod = paymentline.payment_method_id;

        console.log("✅ Payment method seleccionado:", paymentMethod);
        console.log("Card ID:", paymentMethod.card_id);

        if (!paymentMethod) {
            console.warn("⚠️ La línea de pago NO tiene un método asociado.");
            return;
        }

        console.log("🔑 payment_method.id:", paymentMethod.card_id);

        const order = this.env.services.pos.get_order();
        const line = order.get_selected_orderline();

        let originalPriceForInstallments = paymentline.amount;

        if (line) {
            console.log("line ", line)
            if (line.original_unit_price) {
                originalPriceForInstallments = line.original_unit_price * line.qty;
            }
        }

        //const installments = await this.env.services.pos.getInstallments(paymentMethod.card_id, line.price_unit);
        const installments = await this.env.services.pos.getInstallments(paymentMethod.card_id, originalPriceForInstallments);
        console.log("Installments: ", installments);


        const lines = order.get_orderlines();

        // 1️⃣ Obtener los installments para TODAS las líneas ANTES del popup
        let allInstallments = {};

        for (const line of lines) {

            const originalPrice = line.get_product().get_price(order.pricelist, 1);

            allInstallments[line.id] = await this.env.services.pos.getInstallments(
                paymentMethod.card_id,
                originalPrice
            );
        }

        const payload = await makeAwaitable(this.dialog, InfoPopup, {
            title: _t("Custom Popup!"),
            order: order,
            paymentline: paymentline,
            installments: installments[paymentMethod.card_id].installments,   // ✅ los pasamos al popup
            allInstallments: allInstallments,
            getPayload: (payload) => {
                console.log("selected installment:", payload);
            },
        });


    },

    async addNewPaymentLine(paymentMethod) {
        console.log("💳 Método de pago seleccionado:", paymentMethod);

        const card_id = await this.env.services.pos.getCardID(paymentMethod.id);

        console.log("💳 card_id recibido:", card_id);

        // Bloquear si ya existe un pago con tarjeta de crédito
        if (card_id.card_id !== false) {
            const order = this.env.services.pos.get_order();
            const existingCardLine = (order.payment_ids || []).find(
                (pl) => pl.payment_method_id?.card_id
            );
            if (existingCardLine) {
                alert("Ya existe un pago con tarjeta de crédito. Eliminá el pago anterior antes de agregar otra tarjeta.");
                return;
            }
            paymentMethod.card_id = card_id.card_id;
        }

        await super.addNewPaymentLine(paymentMethod);
    },

    get isInstallmentsButtonDisabled() {
        const paymentline = this.currentOrder?.get_selected_paymentline() || this.currentOrder?.selected_paymentline;
        if (!paymentline || !paymentline.payment_method_id) {
            return true;
        }
        const card_id = paymentline.payment_method_id.card_id;
        return card_id === false || card_id === undefined || card_id === null;
    },

    get selectedInstallmentQty() {
        const paymentline = this.currentOrder?.get_selected_paymentline() || this.currentOrder?.selected_paymentline;
        if (!paymentline || !paymentline.payment_method_id) {
            return null;
        }
        let baseLine = paymentline;
        if (paymentline.is_installment) {
            baseLine = (this.currentOrder?.payment_ids || []).find(
                (pl) => pl.payment_method_id?.id === paymentline.payment_method_id?.id && !pl.is_installment
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

