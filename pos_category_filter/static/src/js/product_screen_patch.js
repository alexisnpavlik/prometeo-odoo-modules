/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(ProductScreen.prototype, {
    /** Ids de las categorías de producto configuradas en la caja (llegan como registros o ids). */
    _categoryFilterIds() {
        return (this.pos.config.category_filter_ids || []).map((categ) =>
            typeof categ === "object" ? categ.id : categ
        );
    },

    /** Ids que se cargan solo como componente de un pack/combo: no se muestran ni se venden sueltos. */
    _categoryHiddenIds() {
        return new Set(
            (this.pos.config.category_filter_hidden_product_ids || []).map((product) =>
                typeof product === "object" ? product.id : product
            )
        );
    },

    get products() {
        const hidden = this._categoryHiddenIds();
        const products = super.products;
        return hidden.size ? products.filter((product) => !hidden.has(product.id)) : products;
    },

    /** "Buscar más" consulta el servidor: le suma el filtro por categoría de la caja. */
    loadProductFromDBDomain(searchProductWord) {
        const domain = super.loadProductFromDBDomain(searchProductWord);
        const mode = this.pos.config.category_filter_mode;
        const ids = this._categoryFilterIds();
        if (mode === "all" || !ids.length) {
            return domain;
        }
        const leaf = ["categ_id", "child_of", ids];
        return mode === "include" ? [...domain, leaf] : [...domain, "!", leaf];
    },

    /** Código de un producto que la caja no vende: aviso propio en lugar de "no encontrado". */
    async _barcodeProductAction(code) {
        const product = await this._getProductByBarcode(code);
        if (product && this._categoryHiddenIds().has(product.id)) {
            this.sound.play("error");
            this.notification.add(_t("Producto no habilitado en esta caja"), { type: "warning" });
            return;
        }
        if (!product && this.pos.config.category_filter_mode !== "all") {
            const blocked = await this.pos.data.call("pos.config", "is_barcode_blocked_by_category", [
                [this.pos.config.id],
                code.base_code,
            ]);
            if (blocked) {
                this.sound.play("error");
                this.notification.add(_t("Producto no habilitado en esta caja"), { type: "warning" });
                return;
            }
        }
        return super._barcodeProductAction(code);
    },
});
