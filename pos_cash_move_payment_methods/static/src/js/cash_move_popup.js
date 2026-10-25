/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CashMovePopup } from "@point_of_sale/app/navbar/cash_move_popup/cash_move_popup";

patch(CashMovePopup.prototype, {
    setup() {
        super.setup(...arguments);
        const cash = this.moveMethods.find((pm) => pm.type === "cash");
        this.state.paymentMethodId = (cash || this.moveMethods[0])?.id;
    },

    /**
     * Métodos de la caja habilitados para ingresos/retiros: efectivo + los marcados.
     */
    get moveMethods() {
        return this.pos.config.payment_method_ids.filter(
            (pm) => pm.type === "cash" || (pm.type === "bank" && pm.allow_cash_in_out)
        );
    },

    _prepare_try_cash_in_out_payload(type, amount, reason, extras) {
        const payload = super._prepare_try_cash_in_out_payload(...arguments);
        payload[4] = { ...payload[4], payment_method_id: this.state.paymentMethodId };
        return payload;
    },
});
