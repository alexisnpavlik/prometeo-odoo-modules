/** @odoo-module **/

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";

/** Redondea `price` al múltiplo `step` según `method` (nearest | up | down). */
export function roundToStep(price, step, method) {
    if (!step || step <= 1) {
        return price;
    }
    // El epsilon evita que 3450 quede como 3449.9999 por error de coma flotante.
    const ratio = price / step;
    const eps = 1e-9;
    if (method === "up") {
        return Math.ceil(ratio - eps) * step;
    }
    if (method === "down") {
        return Math.floor(ratio + eps) * step;
    }
    return Math.floor(ratio + 0.5 + eps) * step;
}

patch(PosOrderline.prototype, {
    setOptions(options) {
        const code = options?.code;
        const company = this.order_id?.company_id || this.models["res.company"].getFirst();
        if (code?.type === "price" && company?.barcode_price_rounding_enabled) {
            options = {
                ...options,
                code: {
                    ...code,
                    value: roundToStep(
                        code.value,
                        company.barcode_price_rounding_step,
                        company.barcode_price_rounding_method
                    ),
                },
            };
        }
        return super.setOptions(options);
    },
});
