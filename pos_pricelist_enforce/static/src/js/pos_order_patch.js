/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    /**
     * Corrige el bug intermitente de Odoo POS donde una orden no aplica su lista
     * de precios y las líneas quedan a precio público (lst_price) en vez del fijo
     * de la regla. Re-aplica el precio de lista a cada línea de producto que
     * tenga una regla de tipo precio fijo > 0, de forma quirúrgica:
     * no toca precios editados a mano, líneas de descuento/recargo, combos ni
     * devoluciones. Devuelve la cantidad de líneas corregidas.
     */
    _enforcePricelistFixedPrice() {
        const pricelist = this.pricelist_id;
        if (!pricelist) {
            return 0;
        }
        const discountProduct = this.config.discount_product_id;
        const surchargeProduct = this.config.surcharge_product_id;
        let corrected = 0;

        for (const line of this.get_orderlines()) {
            const product = line.get_product();
            if (!product) {
                continue;
            }
            // No tocar: precio editado a mano.
            if (line.price_type === "manual") {
                continue;
            }
            // No tocar: líneas de descuento global / recargo.
            if (discountProduct && product.id === discountProduct.id) {
                continue;
            }
            if (surchargeProduct && product.id === surchargeProduct.id) {
                continue;
            }
            // No tocar: combos ni devoluciones.
            if (line.combo_parent_id || (line.combo_line_ids && line.combo_line_ids.length)) {
                continue;
            }
            if (line.get_quantity() < 0 || line.refunded_orderline_id) {
                continue;
            }
            // No tocar: líneas cuyo precio gestiona card_installment (recargo por
            // cuotas). Marca sus líneas con original_unit_price; si lo pisáramos,
            // borraríamos el recargo. Si el módulo no está instalado, es undefined.
            if (line.original_unit_price) {
                continue;
            }

            const qty = line.get_quantity();
            const rule = product.getPricelistRule(pricelist, qty);
            // Solo reglas de precio fijo > 0 (respeta las reglas en 0 = público).
            if (!rule || rule.compute_price !== "fixed" || !(rule.fixed_price > 0)) {
                continue;
            }

            const correct = product.get_price(pricelist, qty, line.get_price_extra());
            const current = line.get_unit_price();
            const eps = (line.currency?.rounding || 0.01) / 2;
            if (Math.abs(current - correct) > eps) {
                line.set_unit_price(correct);
                corrected += 1;
            }
        }
        return corrected;
    },
});
