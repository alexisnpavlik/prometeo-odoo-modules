/** @odoo-module **/

import { NumberPopup } from "@point_of_sale/app/utils/input_popups/number_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { parseFloat as parseLocalizedFloat } from "@web/views/fields/parsers";
import { formatFloat } from "@web/core/utils/numbers";
import { _t } from "@web/core/l10n/translation";

export const WEIGHT_BY_AMOUNT = "weight_by_amount";

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

/**
 * Línea seleccionada si su producto no se vende por unidad (kg, litro, metro...).
 * Odoo marca como agrupable solo la categoría Unidad; Units tiene rounding 0,01,
 * así que el redondeo no sirve para distinguirlas.
 */
export function weightByAmountLine(pos) {
    const line = pos.get_order()?.get_selected_orderline();
    const unit = line?.product_id?.uom_id;
    if (!line || !unit || line.get_quantity() < 0 || line.isPartOfCombo()) {
        return null;
    }
    return unit.is_pos_groupable ? null : line;
}

/**
 * Pide el importe y fija la cantidad de la línea = importe / precio unitario.
 * `component` necesita pos, dialog, notification y env (ProductScreen o ControlButtons).
 */
export async function chargeByAmount(component) {
    const { pos, dialog, notification, env } = component;
    const line = weightByAmountLine(pos);
    if (!line) {
        return;
    }
    const unitPrice = line.get_unit_display_price();
    if (!(unitPrice > 0)) {
        notification.add(_t("El producto no tiene precio: no se puede calcular la cantidad."), {
            type: "warning",
        });
        return;
    }
    const unitName = line.product_id.uom_id.name;
    const formatQty = (qty) => formatFloat(qty, { digits: [69, 3] });
    const amount = await makeAwaitable(dialog, NumberPopup, {
        title: _t("Importe a cobrar"),
        subtitle: _t("%(product)s · %(price)s por %(unit)s", {
            product: line.get_full_product_name(),
            price: env.utils.formatCurrency(unitPrice),
            unit: unitName,
        }),
        formatDisplayedValue: (value) => `${pos.currency.symbol} ${value}`,
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
            notification.add(result.body, { title: result.title, type: "danger" });
        }
        return;
    }
    adjustPriceToAmount(line, parsed);
}
