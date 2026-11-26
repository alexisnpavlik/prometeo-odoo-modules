/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { WEIGHT_BY_AMOUNT, chargeByAmount, weightByAmountLine } from "./weight_by_amount";

patch(ProductScreen.prototype, {
    /**
     * En escritorio la tecla Cant. pasa a la fila de botones de arriba (ver control_buttons.xml)
     * y en su lugar del teclado va "Por $". En celular la fila de arriba no existe:
     * el teclado queda como está y "Por $" va al popup de Acciones.
     */
    getNumpadButtons() {
        const buttons = super.getNumpadButtons();
        if (this.ui.isSmall) {
            return buttons;
        }
        return buttons.map((button) =>
            button.value === "quantity"
                ? {
                      value: WEIGHT_BY_AMOUNT,
                      text: _t("Por $"),
                      class: "o_weight_by_amount_button numpad-qty rounded-0 rounded-top mb-0",
                      disabled: !weightByAmountLine(this.pos),
                  }
                : button
        );
    },

    onNumpadClick(buttonValue) {
        if (buttonValue === WEIGHT_BY_AMOUNT) {
            return chargeByAmount(this);
        }
        return super.onNumpadClick(buttonValue);
    },
});
