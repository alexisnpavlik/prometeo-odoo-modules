/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    get currentDiscountPercent() {
        const order = this.pos.get_order();
        if (!order) {
            return 0;
        }
        const discountProduct = this.pos.config.discount_product_id;
        if (!discountProduct) {
            return 0;
        }
        const lines = order.get_orderlines();
        if (!lines || lines.length === 0) {
            return 0;
        }

        const discountLines = lines.filter(line => line.get_product() === discountProduct);
        if (discountLines.length === 0) {
            return 0;
        }

        const totalDiscountAmount = order.calculate_base_amount(discountLines);
        const baseLines = lines.filter(line => line.get_product() !== discountProduct && line.isGlobalDiscountApplicable());
        const totalBaseAmount = order.calculate_base_amount(baseLines);

        if (totalBaseAmount <= 0) {
            return 0;
        }

        // Calcular el porcentaje real y redondear a 1 decimal
        const pc = (-totalDiscountAmount / totalBaseAmount) * 100;
        return Math.round(pc * 10) / 10;
    }
});
