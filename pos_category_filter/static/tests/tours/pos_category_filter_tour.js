/** @odoo-module **/

import * as ProductScreen from "@point_of_sale/../tests/tours/utils/product_screen_util";
import * as Dialog from "@point_of_sale/../tests/tours/utils/dialog_util";
import * as Chrome from "@point_of_sale/../tests/tours/utils/chrome_util";
import { scan_barcode } from "@point_of_sale/../tests/tours/utils/common";
import { ProductScreen as ProductScreenComponent } from "@point_of_sale/app/screens/product_screen/product_screen";
import { registry } from "@web/core/registry";

function fail(message) {
    throw new Error(`pos_category_filter: ${message}`);
}

function orderProductNames() {
    return window.posmodel
        .get_order()
        .get_orderlines()
        .map((line) => line.get_product().display_name);
}

registry.category("web_tour.tours").add("pos_category_filter_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.productIsDisplayed("CF Pelota"),
            {
                content: "sin barra de categorías y sin productos de otras categorías",
                trigger: ".product-list .product-name:contains('CF Pelota')",
                run: () => {
                    if (document.querySelector(".category-list")) {
                        fail("la barra de categorías sigue visible");
                    }
                    const names = [...document.querySelectorAll(".product-list .product-name")].map(
                        (el) => el.textContent.trim()
                    );
                    if (names.some((name) => name.includes("CF Collar"))) {
                        fail("se muestra un producto excluido");
                    }
                },
            },
            scan_barcode("7790003"),
            {
                content: "aviso de producto no habilitado",
                trigger: ".o_notification:contains('Producto no habilitado en esta caja')",
            },
            {
                content: "el producto excluido no entró al pedido",
                trigger: ".pos",
                run: () => {
                    if (orderProductNames().some((name) => name.includes("CF Collar"))) {
                        fail("el escaneo agregó un producto excluido");
                    }
                },
            },
            scan_barcode("7790001"),
            ProductScreen.selectedOrderlineHas("CF Pelota", "1"),
            {
                content: "Buscar más no trae productos excluidos",
                trigger: ".pos",
                run: async () => {
                    const domain = ProductScreenComponent.prototype.loadProductFromDBDomain.call(
                        { pos: window.posmodel, _categoryFilterIds: ProductScreenComponent.prototype._categoryFilterIds },
                        "CF Collar"
                    );
                    const found = await window.posmodel.data.searchRead("product.product", domain, ["id"]);
                    if (found.length) {
                        fail("Buscar más devolvió un producto excluido");
                    }
                },
            },
        ].flat(),
});
