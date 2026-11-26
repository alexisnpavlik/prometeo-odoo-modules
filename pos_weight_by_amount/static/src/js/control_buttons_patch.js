/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { chargeByAmount, weightByAmountLine } from "./weight_by_amount";

patch(ControlButtons.prototype, {
    setup() {
        super.setup();
        this.numberBuffer = useService("number_buffer");
    },

    get hasSelectedLine() {
        return Boolean(this.currentOrder?.get_selected_orderline());
    },

    get weightByAmountLine() {
        return weightByAmountLine(this.pos);
    },

    /**
     * Tecla Cant. movida desde el teclado: mismo efecto que ProductScreen.onNumpadClick("quantity").
     */
    clickQuantityMode() {
        this.numberBuffer.capture();
        this.numberBuffer.reset();
        this.pos.numpadMode = "quantity";
    },

    async clickWeightByAmount() {
        this.props.close?.();
        await chargeByAmount(this);
    },
});
