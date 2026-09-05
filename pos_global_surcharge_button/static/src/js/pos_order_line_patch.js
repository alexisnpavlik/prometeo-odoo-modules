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

    /** True si la línea forma parte de una devolución: o es una línea de
     *  reembolso generada desde el ticket original, o el pedido ya tiene algún
     *  producto (que no sea el propio recargo) en negativo. Solo en ese contexto
     *  tiene sentido un recargo negativo: se está reintegrando un recargo que ya
     *  se cobró. En una venta normal sigue bloqueado, que es lo que evita que el
     *  cajero use el recargo como descuento encubierto. */
    get _isSurchargeReturnContext() {
        if (this.refunded_orderline_id) {
            return true;
        }
        const surchargeProductId = this.config.surcharge_product_id?.id;
        const lines = this.order_id?.get_orderlines?.() || [];
        return lines.some(
            (line) =>
                line.product_id?.id !== surchargeProductId &&
                (Boolean(line.refunded_orderline_id) || line.get_quantity() < 0)
        );
    },

    /** Bloquea la cantidad negativa en la línea de recargo. Pulsar +/- en el
     *  numpad negaría la cantidad y el recargo pasaría a ser un descuento.
     *  Se devuelve el objeto de error que `_setValue` muestra como popup y que
     *  hace que la cantidad no se modifique. En una devolución sí se permite. */
    set_quantity(quantity, keep_price) {
        if (this._isSurchargeLine && !this._isSurchargeReturnContext) {
            const quant =
                typeof quantity === "number" ? quantity : parseFloat("" + (quantity || 0));
            if (quant < 0) {
                return {
                    title: _t("Recargo inválido"),
                    body: _t(
                        "El recargo no puede tener cantidad negativa: se convertiría en un descuento. Para devolver un recargo, cargá primero el producto devuelto en negativo."
                    ),
                };
            }
        }
        return super.set_quantity(quantity, keep_price);
    },

    /** Bloquea el precio unitario negativo en la línea de recargo (mismo efecto
     *  que la cantidad negativa, pero por el modo Precio del numpad). Igual que
     *  arriba, en una devolución se permite. */
    set_unit_price(price) {
        if (this._isSurchargeLine && !this._isSurchargeReturnContext) {
            const parsed = parseFloat("" + price);
            if (!isNaN(parsed) && parsed < 0) {
                return;
            }
        }
        return super.set_unit_price(price);
    },
});
