/** @odoo-module **/

import * as ProductScreen from "@point_of_sale/../tests/tours/utils/product_screen_util";
import * as NumberPopup from "@point_of_sale/../tests/tours/utils/number_popup_util";
import * as Dialog from "@point_of_sale/../tests/tours/utils/dialog_util";
import * as Chrome from "@point_of_sale/../tests/tours/utils/chrome_util";
import { registry } from "@web/core/registry";

function fail(message) {
    throw new Error(`pos_weight_by_amount: ${message}`);
}

function selectedLine() {
    return window.posmodel.get_order().get_selected_orderline();
}

function chargeAmount(amount) {
    return [
        {
            content: "abrir $ → kg",
            trigger: ".o_weight_by_amount_button:not([disabled])",
            run: "click",
        },
        NumberPopup.enterValue(amount),
        Dialog.confirm("Calcular"),
    ].flat();
}

function expectLine(name, amount, listPrice) {
    return {
        content: `${name}: total ${amount}`,
        trigger: ".pos",
        run: () => {
            const line = selectedLine();
            if (!line.get_full_product_name().includes(name)) {
                fail(`línea seleccionada inesperada: ${line.get_full_product_name()}`);
            }
            // La cantidad es importe / precio redondeada a la precisión de la UdM (0,01 kg).
            const rounding = Math.max(line.product_id.uom_id.rounding, 0.01);
            if (Math.abs(line.get_quantity() - amount / listPrice) > rounding / 2 + 1e-9) {
                fail(`cantidad ${line.get_quantity()} lejos de ${amount / listPrice}`);
            }
            if (Math.abs(line.get_display_price() - amount) > 0.01) {
                fail(`total ${line.get_display_price()}, se esperaba ${amount}`);
            }
        },
    };
}

registry.category("web_tour.tours").add("pos_weight_by_amount_tour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.clickDisplayedProduct("PWA Unidad"),
            {
                content: "producto por unidad: botón deshabilitado",
                trigger: ".o_weight_by_amount_button[disabled]",
            },
            {
                content: "fila de arriba: Nota interna oculta",
                trigger: ".control-buttons .o_qty_mode_button",
                run: () => {
                    const note = document.querySelector(".control-buttons .o_line_note_button");
                    if (note && note.offsetParent !== null) {
                        fail("Nota interna sigue visible en la fila de arriba");
                    }
                },
            },
            {
                content: "Cant. en la fila de arriba cambia el teclado a modo cantidad",
                trigger: ".control-buttons .o_qty_mode_button",
                run: "click",
            },
            {
                content: "modo cantidad activo",
                trigger: ".control-buttons .o_qty_mode_button.active",
                run: () => {
                    if (window.posmodel.numpadMode !== "quantity") {
                        fail(`numpadMode = ${window.posmodel.numpadMode}`);
                    }
                },
            },
            ProductScreen.clickDisplayedProduct("PWA Queso"),
            // 5000 / 8000 = 0,625 kg → 0,63 kg y precio ajustado para que dé 5000
            chargeAmount("5000"),
            expectLine("PWA Queso", 5000, 8000),
            // Segunda vez sobre la misma línea (ya con precio manual): parte del precio ajustado
            chargeAmount("1000"),
            expectLine("PWA Queso", 1000, 8000),
            // 3333 / 7000 = 0,476 kg → 0,48 kg
            ProductScreen.clickDisplayedProduct("PWA Fiambre"),
            chargeAmount("3333"),
            expectLine("PWA Fiambre", 3333, 7000),
        ].flat(),
});
