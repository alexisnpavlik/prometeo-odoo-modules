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
    },

    set_amount(amount) {
        const order = this.order || (this.pos || this.env?.services?.pos)?.get_order();
        if (order && !order.is_applying_installment) {
            const hasInstallment = (order.payment_ids || []).some(pl => pl.is_installment);
            if (hasInstallment && this.payment_method_id?.card_id && !this.is_installment) {
                const installmentLine = (order.payment_ids || []).find(pl => pl.is_installment);
                if (installmentLine) {
                    order.remove_paymentline(installmentLine);
                }
            }
        }
        return super.set_amount(amount);
    }
});
