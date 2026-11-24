/** @odoo-module **/

import * as ProductScreen from "@point_of_sale/../tests/tours/utils/product_screen_util";
import * as Dialog from "@point_of_sale/../tests/tours/utils/dialog_util";
import * as Chrome from "@point_of_sale/../tests/tours/utils/chrome_util";
import { registry } from "@web/core/registry";

function fail(message) {
    throw new Error(`pos_promotions: ${message}`);
}

function order() {
    return window.posmodel.get_order();
}

/** Resumen comparable de los hints: [{name, missing: ["1 PH Vaso"], saving}]. */
function hints() {
    return order()
        .getPromotionHints()
        .map((hint) => ({
            name: hint.name,
            tmplId: hint.tmplId,
            missing: hint.missing.map((m) => `${m.qty} ${m.product.display_name}`),
            saving: Math.round(hint.saving),
        }));
}

function expectHints(content, expected) {
    return {
        content,
        trigger: ".product-list",
        run: () => {
            const got = hints().map(({ name, missing, saving }) => ({ name, missing, saving }));
            if (JSON.stringify(got) !== JSON.stringify(expected)) {
                fail(`${content}: esperaba ${JSON.stringify(expected)}, hay ${JSON.stringify(got)}`);
            }
        },
    };
}

const VASOS = { name: "Promo 2 Vasos", missing: ["1 PH Vaso"], saving: 300 };
const FERNET = { name: "Promo Fernet Coca", missing: ["1 PH Coca"], saving: 1200 };

registry.category("web_tour.tours").add("pos_promotion_hints_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("1 Vaso: falta otro", [VASOS]),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("2 Vasos: promo aplicada, sin hint", []),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("3 Vasos: sobra 1, falta otro", [VASOS]),
            ProductScreen.clickDisplayedProduct("PH Fernet"),
            expectHints("Fernet: primero la que más ahorra", [FERNET, VASOS]),
            {
                content: "el último producto agregado abre su promo",
                trigger: ".product-list",
                run: () => {
                    const fernet = hints().find((hint) => hint.name === FERNET.name);
                    if (order().uiState.openPromotionHintTmplId !== fernet.tmplId) {
                        fail(`abierta ${order().uiState.openPromotionHintTmplId}, esperaba ${fernet.tmplId}`);
                    }
                    window.__phOpen = fernet.tmplId;
                },
            },
            ProductScreen.clickDisplayedProduct("PH Agua"),
            expectHints("Agua cara no ahorra: no aparece", [FERNET, VASOS]),
            {
                content: "un producto sin promo sugerida no cambia la abierta",
                trigger: ".product-list",
                run: () => {
                    if (order().uiState.openPromotionHintTmplId !== window.__phOpen) {
                        fail("cambió la promo abierta");
                    }
                },
            },
            ProductScreen.clickLine("PH Fernet"),
            ProductScreen.addDiscount("10"),
            {
                content: "esperar el descuento en la línea",
                trigger: ".orderline.selected:contains('PH Fernet') em:contains('10')",
            },
            expectHints("descuento manual en Fernet: deja de contar", [VASOS]),
        ].flat(),
});
