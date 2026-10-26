/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    /** Si el POS limita categorías, muestra igual los packs aunque no tengan una habilitada. */
    get products() {
        const products = super.products;
        const { limit_categories, iface_available_categ_ids } = this.pos.config;
        if (!limit_categories || !iface_available_categ_ids.length) {
            return products;
        }
        const shown = new Set(products.map((product) => product.id));
        const packs = this.pos.models["product.product"].filter(
            (product) => product.is_promotion_pack && !shown.has(product.id)
        );
        return [...products, ...packs];
    },
});
