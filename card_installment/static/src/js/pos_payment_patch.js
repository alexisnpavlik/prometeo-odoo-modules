/** @odoo-module **/

import { PosPayment } from "@point_of_sale/app/models/pos_payment";
import { patch } from "@web/core/utils/patch";

patch(PosPayment.prototype, {
    export_for_printing() {
        const result = super.export_for_printing();
        // Include installment_name in the receipt data if it exists
        if (this.installment_name) {
            result.installment_name = this.installment_name;
            result.name = this.installment_name;
        }
        return result;
    }
});
