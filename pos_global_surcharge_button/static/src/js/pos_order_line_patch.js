/** @odoo-module **/

import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PosOrderline.prototype, {
    /** True si esta línea corresponde al producto de recargo global. */
    get _isSurchargeLine() {
        const surchargeProduct = this.config.surcharge_product_id;
        return Boolean(surchargeProduct) && this.product_id?.id === surchargeProduct.id;
    },

    /** Bloquea la cantidad negativa en la línea de recargo. Pulsar +/- en el
     *  numpad negaría la cantidad y el recargo pasaría a ser un descuento.
     *  Se devuelve el objeto de error que `_setValue` muestra como popup y que
     *  hace que la cantidad no se modifique. */
    set_quantity(quantity, keep_price) {
        if (this._isSurchargeLine) {
            const quant =
                typeof quantity === "number" ? quantity : parseFloat("" + (quantity || 0));
            if (quant < 0) {
                return {
                    title: _t("Recargo inválido"),
                    body: _t(
                        "El recargo no puede tener cantidad negativa: se convertiría en un descuento."
                    ),
                };
            }
        }
        return super.set_quantity(quantity, keep_price);
    },

    /** Bloquea el precio unitario negativo en la línea de recargo (mismo efecto
     *  que la cantidad negativa, pero por el modo Precio del numpad). */
    set_unit_price(price) {
        if (this._isSurchargeLine) {
            const parsed = parseFloat("" + price);
            if (!isNaN(parsed) && parsed < 0) {
                return;
            }
        }
        return super.set_unit_price(price);
    },
});
