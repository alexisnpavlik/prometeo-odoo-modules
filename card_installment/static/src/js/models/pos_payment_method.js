/** @odoo-module **/

import { PosPaymentMethod } from "@point_of_sale/models/pos_payment_method";
import { patch } from "@web/core/utils/patch";

patch(PosPaymentMethod.prototype, {
    setup() {
        super.setup();
        // Asegura que se cargue el campo card_id en los datos del POS
        this.card_id = this.data.card_id || false;
    },
});
