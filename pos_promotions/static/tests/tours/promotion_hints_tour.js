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
            missing: hint.missing.map((m) => `${m.qty} ${m.product.name}`),
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

function dom(content, check) {
    return { content, trigger: ".product-list", run: () => check() || undefined };
}

const DOT = ".o_promotion_hints .o_promotion_hint_dot";
const CARD = ".o_promotion_hints .o_promotion_hint_card";

const VASOS = { name: "Promo 2 Vasos", missing: ["1 PH Vaso"], saving: 300 };
const FERNET = { name: "Promo Fernet Coca", missing: ["1 PH Coca"], saving: 1200 };

registry.category("web_tour.tours").add("pos_promotion_hints_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("1 Vaso: falta otro", [VASOS]),
            { content: "aparece el círculo con iniciales", trigger: `${DOT} .o_promotion_hint_initials:contains('PH')` },
            { content: "pastilla con el ahorro", trigger: `${DOT} .o_promotion_hint_saving:contains('300')` },
            { content: "burbuja abierta con el texto", trigger: `${CARD}:contains('Sumá 1 PH Vaso'):contains('Ahorra')` },
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("2 Vasos: promo aplicada, sin hint", []),
            dom("sin círculos con la promo completa", () => {
                if (document.querySelector(DOT)) {
                    fail("quedó un círculo con la promo completa");
                }
            }),
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
            { content: "dos círculos", trigger: `${DOT}:nth-child(2)` },
            { content: "el activo (Coca) muestra la foto", trigger: `${DOT}.o_promotion_hint_dot_active img` },
            { content: "la burbuja abierta es la de Fernet", trigger: `${CARD}:contains('Sumá 1 PH Coca'):contains('Promo Fernet Coca')` },
            dom("guardar cantidad de líneas", () => {
                window.__phLines = order().get_orderlines().length;
            }),
            { content: "tocar el círculo de Vasos", trigger: `${DOT}:not(.o_promotion_hint_dot_active)`, run: "click" },
            { content: "se abre la de Vasos", trigger: `${CARD}:contains('Promo 2 Vasos')` },
            { content: "tocar el círculo activo", trigger: `${DOT}.o_promotion_hint_dot_active`, run: "click" },
            dom("la burbuja se cierra sin descartar la promo", () => {
                if (document.querySelector(CARD)) {
                    fail("tocar el círculo activo no cerró la burbuja");
                }
                if (document.querySelectorAll(DOT).length !== 2 || !hints().some((h) => h.name === VASOS.name)) {
                    fail("cerrar la burbuja descartó la promo");
                }
            }),
            { content: "volver a abrir Vasos", trigger: `${DOT}:not(.o_promotion_hint_dot_active):last`, run: "click" },
            { content: "Vasos abierta otra vez", trigger: `${CARD}:contains('Promo 2 Vasos')` },
            { content: "tocar la burbuja abierta", trigger: CARD, run: "click" },
            dom("tocar no agrega nada a la orden", () => {
                if (order().get_orderlines().length !== window.__phLines) {
                    fail("tocar la burbuja cambió la orden");
                }
            }),
            { content: "descartar la de Vasos", trigger: `${CARD} .o_promotion_hint_close`, run: "click" },
            dom("queda un círculo y Vasos ya no está", () => {
                if (document.querySelectorAll(DOT).length !== 1) {
                    fail(`hay ${document.querySelectorAll(DOT).length} círculos, esperaba 1`);
                }
                if (hints().some((hint) => hint.name === VASOS.name)) {
                    fail("la promo descartada sigue en los hints");
                }
            }),
            { content: "reabrir Fernet para seguir", trigger: DOT, run: "click" },
            ProductScreen.clickDisplayedProduct("PH Agua"),
            expectHints("Agua cara no ahorra: no aparece", [FERNET]),
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
            expectHints("descuento manual en Fernet: deja de contar", []),
            Chrome.createFloatingOrder(),
            dom("orden nueva: sin círculos", () => {
                if (document.querySelector(DOT)) {
                    fail("la orden nueva arrastró círculos");
                }
            }),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("orden nueva: lo descartado no se arrastra", [VASOS]),
            { content: "círculo en la orden nueva", trigger: DOT },
        ].flat(),
});
