/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";

patch(ControlButtons.prototype, {
    /** Devuelve las líneas del pedido que son del producto de recargo. */
    _getSurchargeLines() {
        const order = this.pos.get_order();
        const product = this.pos.config.surcharge_product_id;
        if (!order || !product) {
            return [];
        }
        return order
            .get_orderlines()
            .filter((line) => line.get_product() === product);
    },

    /** Base sobre la que se calcula el recargo: líneas de producto aplicables,
     *  excluyendo la línea de recargo y la de descuento global. */
    _getSurchargeBase() {
        const order = this.pos.get_order();
        if (!order) {
            return 0;
        }
        const product = this.pos.config.surcharge_product_id;
        const discountProduct = this.pos.config.discount_product_id;
        const baseLines = order.get_orderlines().filter(
            (line) =>
                line.get_product() !== product &&
                line.get_product() !== discountProduct &&
                line.isGlobalDiscountApplicable()
        );
        return order.calculate_base_amount(baseLines);
    },

    /** Porcentaje de recargo actualmente aplicado, para el badge. */
    get currentSurchargePercent() {
        const surchargeLines = this._getSurchargeLines();
        if (surchargeLines.length === 0) {
            return 0;
        }
        const order = this.pos.get_order();
        const totalSurcharge = order.calculate_base_amount(surchargeLines);
        const base = this._getSurchargeBase();
        if (base <= 0) {
            return 0;
        }
        const pc = (totalSurcharge / base) * 100;
        return Math.round(pc * 10) / 10;
    },

    /** Toggle del recargo global: si hay línea de recargo la quita; si no, la agrega. */
    async clickSurcharge() {
        const order = this.pos.get_order();
        const product = this.pos.config.surcharge_product_id;
        if (!order || !product) {
            return;
        }
        const existing = this._getSurchargeLines();
        if (existing.length > 0) {
            for (const line of existing) {
                line.delete();
            }
            return;
        }
        const base = this._getSurchargeBase();
        const amount = (this.pos.config.surcharge_pc / 100.0) * base;
        if (amount > 0) {
            await this.pos.addLineToCurrentOrder(
                { product_id: product, price_unit: amount },
                { merge: false }
            );
        }
    },
});
