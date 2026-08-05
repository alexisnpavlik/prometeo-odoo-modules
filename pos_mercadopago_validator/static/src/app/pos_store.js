/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { PosStore, register_payment_method } from "@point_of_sale/app/store/pos_store";
import { PaymentMercadoPagoValidator } from "@pos_mercadopago_validator/app/payment_mercadopago_validator";
import { inboxListeners } from "@pos_mercadopago_validator/app/inbox_dialog";

register_payment_method("mercadopago_validator", PaymentMercadoPagoValidator);

patch(PosStore.prototype, {
    /**
     * Abre una única suscripción al bus de la bandeja para toda la sesión.
     *
     * `connectWebSocket` no tiene contraparte para desuscribirse, así que el
     * canal se abre acá y los diálogos de cobro se anotan en `inboxListeners`
     * mientras están vivos.
     */
    async setup() {
        await super.setup(...arguments);
        this.data.connectWebSocket("MERCADOPAGO_INBOX_UPDATED", (payload) => {
            if (payload.config_id !== this.config.id) {
                return;
            }
            for (const listener of inboxListeners) {
                listener(payload);
            }
        });
    },
});
