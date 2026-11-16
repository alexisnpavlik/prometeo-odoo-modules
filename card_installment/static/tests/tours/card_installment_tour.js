/** @odoo-module **/

import * as ProductScreen from "@point_of_sale/../tests/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/tours/utils/payment_screen_util";
import * as Dialog from "@point_of_sale/../tests/tours/utils/dialog_util";
import * as Chrome from "@point_of_sale/../tests/tours/utils/chrome_util";
import * as ReceiptScreen from "@point_of_sale/../tests/tours/utils/receipt_screen_util";
import { registry } from "@web/core/registry";

const CARD = "Tarjeta Test";

function order() {
    return window.posmodel.get_order();
}

function round2(value) {
    return Math.round(value * 100) / 100;
}

function linePrices() {
    return order()
        .get_orderlines()
        .map((line) => round2(line.get_unit_price()));
}

function fail(message) {
    throw new Error(`card_installment: ${message}`);
}

/** Abre la caja y agrega los productos indicados. */
function openAndAdd(...products) {
    return [
        Chrome.startPoS(),
        Dialog.confirm("Open Register"),
        ...products.map((name) => ProductScreen.clickDisplayedProduct(name)),
    ].flat();
}

/** Aplica el descuento global de pos_discount (porcentaje por defecto de la caja). */
function globalDiscount() {
    return [ProductScreen.clickControlButton("Discount"), Dialog.confirm()].flat();
}

/** Guarda los precios unitarios actuales para compararlos después. */
function snapshot(key) {
    return {
        content: `snapshot ${key}`,
        trigger: ".pos",
        run: () => {
            window.__ciSnap = window.__ciSnap || {};
            window.__ciSnap[key] = linePrices();
        },
    };
}

/** Elige un plan en el popup de cuotas y confirma. */
function chooseInstallment(planName) {
    return [
        {
            content: "click Cuotas",
            trigger: "#button_installments:not([disabled])",
            run: "click",
        },
        {
            content: `select ${planName}`,
            trigger: `.modal-body div.border:has(strong:contains("${planName}")) input[name=installment_option]`,
            run: "click",
        },
        {
            content: "confirm installment popup",
            trigger: ".modal-footer button.o-default-button",
            run: "click",
        },
    ];
}

/** Verifica precios unitarios (en el orden de las líneas) y total de la orden. */
function checkOrder({ prices = null, sameAs = null, total = null }) {
    return {
        content: `check order prices=${JSON.stringify(prices || sameAs)} total=${total}`,
        trigger: "body:not(:has(.modal))",
        run: () => {
            const actual = linePrices();
            const expected = prices || window.__ciSnap[sameAs];
            if (JSON.stringify(actual) !== JSON.stringify(expected)) {
                fail(`precios ${JSON.stringify(actual)} != esperados ${JSON.stringify(expected)}`);
            }
            if (total !== null) {
                const actualTotal = round2(order().get_total_with_tax());
                if (actualTotal !== total) {
                    fail(`total ${actualTotal} != esperado ${total}`);
                }
            }
        },
    };
}

/** Saca la línea de pago con tarjeta (y su recargo) como lo haría el cajero. */
function removeCardPayment() {
    return {
        content: "remove card payment line",
        trigger: ".payment-screen",
        run: () => {
            const line = order().payment_ids.find(
                (pl) => pl.payment_method_id?.card_id && !pl.is_installment
            );
            if (!line) {
                fail("no hay línea de pago con tarjeta");
            }
            order().remove_paymentline(line);
        },
    };
}

// 1. Lista de precios distinta al público + descuento global como última línea,
//    plan sin recargo: nada debe cambiar (el caso de la factura POS/2326).
registry.category("web_tour.tours").add("card_installment_pricelist_discount_last", {
    steps: () =>
        [
            openAndAdd("Mochila A", "Mochila A", "Mochila B", "Mochila B"),
            globalDiscount(),
            checkOrder({ prices: [27000, 19700, -14010], total: 79390 }),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 1"),
            checkOrder({ prices: [27000, 19700, -14010], total: 79390 }),
        ].flat(),
});

// 2. Descuento global en el medio (se agregó un producto después):
//    sin recargo, ninguna línea cambia de precio.
registry.category("web_tour.tours").add("card_installment_discount_not_last", {
    steps: () =>
        [
            openAndAdd("Mochila A"),
            globalDiscount(),
            ProductScreen.clickDisplayedProduct("Mochila B"),
            snapshot("before"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 1"),
            checkOrder({ sameAs: "before" }),
        ].flat(),
});

// 3. Plan con recargo (x1.10) pagando todo con tarjeta: cada línea sube 10%
//    sobre el precio de lista; al sacar la tarjeta vuelven al precio de lista.
registry.category("web_tour.tours").add("card_installment_surcharge_full", {
    steps: () =>
        [
            openAndAdd("Mochila A", "Mochila B"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 6"),
            checkOrder({ prices: [29700, 21670], total: 51370 }),
            removeCardPayment(),
            checkOrder({ prices: [27000, 19700], total: 46700 }),
        ].flat(),
});

// 4. Precio tipeado a mano: las cuotas sin recargo lo respetan.
registry.category("web_tour.tours").add("card_installment_manual_price", {
    steps: () =>
        [
            openAndAdd("Mochila A"),
            {
                content: "set manual price on Mochila A",
                trigger: ".pos",
                run: () => {
                    const line = order().get_selected_orderline();
                    line.price_type = "manual";
                    line.set_unit_price(25000);
                },
            },
            ProductScreen.clickDisplayedProduct("Mochila B"),
            checkOrder({ prices: [25000, 19700], total: 44700 }),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 1"),
            checkOrder({ prices: [25000, 19700], total: 44700 }),
        ].flat(),
});

// 5. Cambiar de plan varias veces no acumula recargos.
registry.category("web_tour.tours").add("card_installment_change_plan", {
    steps: () =>
        [
            openAndAdd("Mochila A", "Mochila B"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 6"),
            checkOrder({ prices: [29700, 21670], total: 51370 }),
            chooseInstallment("Plan 1"),
            checkOrder({ prices: [27000, 19700], total: 46700 }),
            // Al quitar el recargo no queda línea de pago seleccionada (comportamiento
            // previo): el cajero toca la línea de la tarjeta para volver a elegir.
            PaymentScreen.clickPaymentline(CARD, "46,700.00"),
            chooseInstallment("Plan 6"),
            checkOrder({ prices: [29700, 21670], total: 51370 }),
        ].flat(),
});

// 6. Pago mixto: 20.000 en efectivo + resto con tarjeta en 6 cuotas.
//    El recargo se calcula solo sobre la parte de la tarjeta (26.700 x 10%).
registry.category("web_tour.tours").add("card_installment_split_payment", {
    steps: () =>
        [
            openAndAdd("Mochila A", "Mochila B"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Cash"),
            {
                content: "cash pays 20000",
                trigger: ".payment-screen",
                run: () => order().get_selected_paymentline().set_amount(20000),
            },
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 6"),
            checkOrder({ prices: [28335, 21035], total: 49370 }),
        ].flat(),
});

// 7. Venta completa: lista mayorista + descuento global + 6 cuotas, se valida.
//    Las líneas que se graban (y se facturan) deben ser precio de lista x 1.10.
registry.category("web_tour.tours").add("card_installment_validate_order", {
    steps: () =>
        [
            openAndAdd("Mochila A", "Mochila A", "Mochila B", "Mochila B"),
            globalDiscount(),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod(CARD),
            chooseInstallment("Plan 6"),
            checkOrder({ prices: [29700, 21670, -15411], total: 87329 }),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
        ].flat(),
});
