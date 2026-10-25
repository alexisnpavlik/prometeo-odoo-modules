/** @odoo-module **/
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { formatCurrency, roundCurrency } from "@point_of_sale/app/models/utils/currency";
import { accountTaxHelpers } from "@account/helpers/account_tax";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

// La línea valida la forma de sus datos (en modo debug falla con una clave desconocida).
Orderline.props.line.shape.promotion = { type: Boolean, optional: true };

patch(PosOrderline.prototype, {
    /** Precio de venta del producto sin lista de precios, con impuestos según la config del POS. */
    getPromotionOriginalPrice() {
        const baseLine = accountTaxHelpers.prepare_base_line_for_taxes_computation(
            this,
            this.prepareBaseLineForTaxesComputationExtraValues({
                price_unit: this.product_id.lst_price + (this.price_extra || 0),
                quantity: 1,
                tax_ids: this.product_id.taxes_id,
            })
        );
        accountTaxHelpers.add_tax_details_in_base_line(baseLine, this.company);
        accountTaxHelpers.round_base_lines_tax_details([baseLine], this.company);
        return this.config.iface_tax_included === "total"
            ? baseLine.tax_details.total_included_currency
            : baseLine.tax_details.total_excluded_currency;
    },

    /** Pack: precio por unidad de pack de los productos sueltos y el que se cobra. */
    getPackPrices() {
        const qty = this.get_quantity() || 1;
        const sum = (fn) => this.combo_line_ids.reduce((acc, child) => acc + fn(child) * child.get_quantity(), 0) / qty;
        return {
            original: sum((child) => child.getPromotionOriginalPrice()),
            current: sum((child) => child.get_unit_display_price()),
        };
    },

    /** Indica si a la línea le aplica una regla de la lista que baja el precio de venta,
     * o si es un pack de Promociones más barato que sus productos sueltos. */
    isPromotion() {
        if (this.price_type === "manual" || this.combo_parent_id || this.get_quantity() <= 0) {
            return false;
        }
        if (this.product_id.is_promotion_pack && this.combo_line_ids?.length) {
            const { original, current } = this.getPackPrices();
            return roundCurrency(current, this.currency) < roundCurrency(original, this.currency);
        }
        const rule = this.product_id.getPricelistRule(this.order_id.pricelist_id, this.get_quantity());
        return (
            Boolean(rule) &&
            roundCurrency(this.get_unit_display_price(), this.currency) <
                roundCurrency(this.getPromotionOriginalPrice(), this.currency)
        );
    },

    /** Agrega la marca de promoción y tacha el precio original también en reglas de precio fijo. */
    getDisplayData() {
        const data = super.getDisplayData();
        const promotion = this.isPromotion();
        data.promotion = promotion;
        const isPack = this.product_id.is_promotion_pack && this.combo_line_ids?.length;
        if (isPack) {
            // En un combo Odoo muestra $0 por unidad: el precio lo llevan los productos de abajo.
            data.unitPrice = formatCurrency(this.getPackPrices().current, this.currency);
        }
        if (promotion) {
            const original = isPack ? this.getPackPrices().original : this.getPromotionOriginalPrice();
            data.oldUnitPrice = formatCurrency(original, this.currency);
        }
        return data;
    },
});
