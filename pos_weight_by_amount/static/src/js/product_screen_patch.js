/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { buttonsType } from "@point_of_sale/app/generic_components/numpad/numpad";
import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { parseFloat as parseLocalizedFloat } from "@web/views/fields/parsers";
import { formatFloat } from "@web/core/utils/numbers";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

/**
 * Convierte el texto del teclado (con separador decimal local) a número.
 * Devuelve NaN si no es un número válido.
 */
function parseAmount(value) {
    try {
        return parseLocalizedFloat(String(value ?? ""));
    } catch {
        return NaN;
    }
}

/**
 * Cantidad que corresponde a un importe dado el precio unitario mostrado.
 */
export function quantityForAmount(amount, unitPrice) {
    if (!(amount > 0) || !(unitPrice > 0)) {
        return 0;
    }
    return amount / unitPrice;
}

/**
 * La cantidad se redondea a la precisión de la UdM (en las bases reales 0,01 kg = 10 g),
 * así que el total queda corrido del importe pedido. Se escala el precio unitario para
 * que el total mostrado (con impuestos y descuento) sea el importe exacto.
 * El precio queda como manual para que un cambio de cantidad posterior no lo recalcule.
 */
function adjustPriceToAmount(line, amount) {
    const total = line.get_display_price();
    if (!(total > 0) || Math.abs(total - amount) < 0.005) {
        return;
    }
    line.price_type = "manual";
    line.set_unit_price((line.get_unit_price() * amount) / total);
}

const BUTTON_VALUE = "weight_by_amount";

// El Numpad valida la forma de cada tecla: se habilita la clave opcional subButton
// (una segunda tecla dibujada dentro de la misma celda, ver numpad.xml).
buttonsType.element[0].shape.subButton = {
    type: Object,
    optional: true,
    shape: {
        value: String,
        text: String,
        title: { type: String, optional: true },
        disabled: { type: Boolean, optional: true },
    },
};

patch(ProductScreen.prototype, {
    /**
     * Línea seleccionada si su producto no se vende por unidad (kg, litro, metro...).
     * Odoo marca como agrupable solo la categoría Unidad; Units tiene rounding 0,01,
     * así que el redondeo no sirve para distinguirlas.
     */
    get weightByAmountLine() {
        const line = this.currentOrder?.get_selected_orderline();
        const unit = line?.product_id?.uom_id;
        if (!line || !unit || line.get_quantity() < 0 || line.isPartOfCombo()) {
            return null;
        }
        return unit.is_pos_groupable ? null : line;
    },

    /**
     * Cuelga el botón "Por $" de la tecla Cant.: el template del Numpad lo dibuja
     * dentro de la misma celda (ver numpad.xml).
     */
    getNumpadButtons() {
        return super.getNumpadButtons().map((button) =>
            button.value === "quantity"
                ? {
                      ...button,
                      subButton: {
                          value: BUTTON_VALUE,
                          text: _t("Por $"),
                          title: _t("Cargar la cantidad a partir del importe"),
                          disabled: !this.weightByAmountLine,
                      },
                  }
                : button
        );
    },

    onNumpadClick(buttonValue) {
        if (buttonValue === BUTTON_VALUE) {
            return this.clickWeightByAmount();
        }
        return super.onNumpadClick(buttonValue);
    },

    /**
     * Pide el importe y fija la cantidad de la línea = importe / precio unitario.
     */
    async clickWeightByAmount() {
        const line = this.weightByAmountLine;
        if (!line) {
            return;
        }
        this.numberBuffer.capture();
        this.numberBuffer.reset();
        const unitPrice = line.get_unit_display_price();
        if (!(unitPrice > 0)) {
            this.notification.add(_t("El producto no tiene precio: no se puede calcular la cantidad."), {
                type: "warning",
            });
            return;
        }
        const formatCurrency = this.env.utils.formatCurrency;
        const unitName = line.product_id.uom_id.name;
        const formatQty = (qty) => formatFloat(qty, { digits: [69, 3] });
        const amount = await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Importe a cobrar"),
            subtitle: _t("%(product)s · %(price)s por %(unit)s", {
                product: line.get_full_product_name(),
                price: formatCurrency(unitPrice),
                unit: unitName,
            }),
            formatDisplayedValue: (value) => `${this.pos.currency.symbol} ${value}`,
            feedback: (value) => {
                const qty = quantityForAmount(parseAmount(value), unitPrice);
                return qty ? `≈ ${formatQty(qty)} ${unitName}` : false;
            },
            isValid: (value) => parseAmount(value) > 0,
            confirmButtonLabel: _t("Calcular"),
        });
        const parsed = parseAmount(amount);
        if (!(parsed > 0)) {
            return;
        }
        // set_quantity devuelve true si salió bien, o {title, body} si la rechaza (devoluciones).
        let result = line.set_quantity(quantityForAmount(parsed, unitPrice));
        // La lista de precios puede cambiar el precio según la cantidad: recalcular una vez.
        const newUnitPrice = line.get_unit_display_price();
        if (result === true && newUnitPrice > 0 && newUnitPrice !== unitPrice) {
            result = line.set_quantity(quantityForAmount(parsed, newUnitPrice));
        }
        if (result !== true) {
            if (result?.body) {
                this.notification.add(result.body, { title: result.title, type: "danger" });
            }
            return;
        }
        adjustPriceToAmount(line, parsed);
    },
});
