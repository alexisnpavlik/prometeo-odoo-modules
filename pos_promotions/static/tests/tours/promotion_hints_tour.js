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
const row = (name) => `.o_promotion_hints .o_promotion_hint_row[data-promo='${name}']`;

/** Las filas en orden: [{promo, card: bool, top}] (una fila por promo, círculo a la derecha). */
function rows() {
    return [...document.querySelectorAll(".o_promotion_hints .o_promotion_hint_row")].map((el) => ({
        promo: el.dataset.promo,
        card: Boolean(el.querySelector(".o_promotion_hint_card")),
        top: el.getBoundingClientRect().top,
    }));
}

const VASOS = { name: "Promo 2 Vasos", missing: ["1 PH Vaso"], saving: 300 };
const FERNET = { name: "Promo Fernet Coca", missing: ["1 PH Coca"], saving: 1200 };
// Más cara que los sueltos (2 × 1.000 = 2.000 contra 2.500): se muestra igual, al final y sin ahorro.
const AGUA = { name: "Promo Agua cara", missing: ["1 PH Agua"], saving: -500 };

registry.category("web_tour.tours").add("pos_promotion_hints_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("1 Vaso: falta otro", [VASOS]),
            { content: "aparece el círculo con iniciales", trigger: `${DOT} .o_promotion_hint_initials:contains('PH')` },
            { content: "pastilla con el ahorro", trigger: `${DOT} .o_promotion_hint_saving:contains('300')` },
            { content: "burbuja abierta con el texto", trigger: `${CARD}:contains('+ 1 PH Vaso'):contains('Ahorra')` },
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
            { content: "fila de Fernet con su texto", trigger: `${row(FERNET.name)} .o_promotion_hint_card:contains('+ 1 PH Coca'):contains('Promo Fernet Coca'):contains('Ahorra')` },
            { content: "precio en su propia línea", trigger: `${row(FERNET.name)} .o_promotion_hint_price:contains('Promo Fernet Coca a') + .o_promotion_hint_amount:contains('Ahorra')` },
            dom("texto simple: sin encabezado ni 'Sumá'", () => {
                const text = document.querySelector(row(FERNET.name)).textContent;
                if (/Promo disponible|Sumá/i.test(text)) {
                    fail(`texto viejo: ${text}`);
                }
            }),
            { content: "fila de Vasos con su texto", trigger: `${row(VASOS.name)} .o_promotion_hint_card:contains('+ 1 PH Vaso')` },
            { content: "el círculo de Coca muestra la foto", trigger: `${row(FERNET.name)} .o_promotion_hint_dot img` },
            dom("filas una debajo de otra, todas con su texto y el círculo a la derecha", () => {
                const got = rows();
                if (got.length !== 2 || !got.every((r) => r.card) || !(got[0].top < got[1].top)) {
                    fail(`filas: ${JSON.stringify(got)}`);
                }
                const el = document.querySelector(row(FERNET.name));
                const card = el.querySelector(".o_promotion_hint_card").getBoundingClientRect();
                const dot = el.querySelector(".o_promotion_hint_dot").getBoundingClientRect();
                if (!(card.right <= dot.left + 1)) {
                    fail("el texto no queda a la izquierda del círculo");
                }
                window.__phLines = order().get_orderlines().length;
            }),
            { content: "tocar el círculo de Vasos", trigger: `${row(VASOS.name)} .o_promotion_hint_dot`, run: "click" },
            dom("oculta solo el texto de Vasos, sin descartarla", () => {
                const got = rows();
                if (got.length !== 2 || got.find((r) => r.promo === VASOS.name).card || !got.find((r) => r.promo === FERNET.name).card) {
                    fail(`filas: ${JSON.stringify(got)}`);
                }
                if (!hints().some((h) => h.name === VASOS.name)) {
                    fail("ocultar el texto descartó la promo");
                }
            }),
            { content: "volver a mostrar Vasos", trigger: `${row(VASOS.name)} .o_promotion_hint_dot`, run: "click" },
            { content: "Vasos con su texto otra vez", trigger: `${row(VASOS.name)} .o_promotion_hint_card` },
            { content: "tocar el texto de Vasos", trigger: `${row(VASOS.name)} .o_promotion_hint_card`, run: "click" },
            dom("tocar no agrega nada a la orden", () => {
                if (order().get_orderlines().length !== window.__phLines) {
                    fail("tocar la burbuja cambió la orden");
                }
            }),
            { content: "descartar la de Vasos", trigger: `${row(VASOS.name)} .o_promotion_hint_close`, run: "click" },
            dom("queda una fila y Vasos ya no está", () => {
                if (rows().length !== 1) {
                    fail(`hay ${rows().length} filas, esperaba 1`);
                }
                if (hints().some((hint) => hint.name === VASOS.name)) {
                    fail("la promo descartada sigue en los hints");
                }
            }),
            ProductScreen.clickDisplayedProduct("PH Agua"),
            expectHints("Agua cara: aparece al final, con ahorro negativo", [FERNET, AGUA]),
            { content: "fila de Agua con su precio", trigger: `${row(AGUA.name)} .o_promotion_hint_card:contains('+ 1 PH Agua'):contains('Promo Agua cara')` },
            dom("la promo más cara no dice Ahorra ni lleva pastilla", () => {
                const el = document.querySelector(row(AGUA.name));
                if (el.textContent.includes("Ahorra") || el.querySelector(".o_promotion_hint_saving")) {
                    fail("la promo más cara muestra ahorro");
                }
            }),
            { content: "ocultar el texto de Fernet", trigger: `${row(FERNET.name)} .o_promotion_hint_dot`, run: "click" },
            ProductScreen.clickDisplayedProduct("PH Pan"),
            dom("un producto sin promo no vuelve a mostrar el texto oculto", () => {
                if (rows().find((r) => r.promo === FERNET.name).card) {
                    fail("se volvió a mostrar Fernet");
                }
            }),
            ProductScreen.clickDisplayedProduct("PH Fernet"),
            { content: "agregar un producto de la promo vuelve a mostrar su texto", trigger: `${row(FERNET.name)} .o_promotion_hint_card` },
            // La línea de Fernet quedó seleccionada (último producto): vuelve a 1 y lleva descuento.
            ProductScreen.clickNumpad("1"),
            ProductScreen.selectedOrderlineHas("PH Fernet", "1"),
            ProductScreen.addDiscount("10"),
            {
                content: "esperar el descuento en la línea",
                trigger: ".orderline.selected:contains('PH Fernet') em:contains('10')",
            },
            expectHints("descuento manual en Fernet: deja de contar", [AGUA]),
            Chrome.createFloatingOrder(),
            dom("orden nueva: sin círculos", () => {
                if (document.querySelector(DOT)) {
                    fail("la orden nueva arrastró círculos");
                }
            }),
            ProductScreen.clickDisplayedProduct("PH Vaso"),
            expectHints("orden nueva: lo descartado no se arrastra", [VASOS]),
            { content: "círculo en la orden nueva", trigger: DOT },
            ProductScreen.clickDisplayedProduct("PH Mesa"),
            dom("cada producto que falta en su línea, completo", () => {
                const lines = [...document.querySelectorAll(`${row("Promo Living")} .o_promotion_hint_missing`)];
                const texts = lines.map((el) => el.textContent.trim());
                if (JSON.stringify(texts) !== JSON.stringify(["+ 2 PH Silla de comedor tapizada", "+ 1 PH Lámpara colgante de techo"])) {
                    fail(`líneas: ${JSON.stringify(texts)}`);
                }
                if (lines.some((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)) {
                    fail("un nombre quedó cortado");
                }
            }),
        ].flat(),
});
