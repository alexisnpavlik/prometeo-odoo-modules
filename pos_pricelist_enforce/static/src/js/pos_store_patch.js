/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PosStore.prototype, {
    /**
     * Antes de ir a cobrar, re-aplica la lista de precios a la orden actual para
     * corregir el bug intermitente donde las líneas quedan a precio público.
     * Nunca bloquea el flujo: si algo falla, se cobra igual.
     */
    async pay() {
        try {
            if (this.config.pricelist_enforce) {
                const order = this.get_order();
                if (order) {
                    const corrected = order._enforcePricelistFixedPrice();
                    if (corrected > 0 && this.config.pricelist_enforce_warn) {
                        this.notification.add(
                            _t(
                                "Se corrigieron %s línea(s) al precio de lista. Si aplicaste un descuento global, revisalo.",
                                corrected
                            ),
                            { type: "warning" }
                        );
                    }
                }
            }
        } catch (error) {
            console.error("pos_pricelist_enforce:", error);
        }
        return super.pay(...arguments);
    },
});
