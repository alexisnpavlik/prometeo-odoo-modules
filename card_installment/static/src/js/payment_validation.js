/** @odoo-module */

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {

    async validateOrder(isForceValidate) {
        const order = this.currentOrder;

        if (order) {
            const hasCardPayment = (order.payment_ids || []).some(
                (pl) => pl.payment_method_id && pl.payment_method_id.card_id
            );
            if (hasCardPayment) {
                const orderlines = order.get_orderlines() || [];
                const hasInstallmentSelected = orderlines.some(line => line && line.original_price);
                if (!hasInstallmentSelected) {
                    this.env.services.notification.add(
                        _t("Por favor, seleccione las cuotas antes de validar la orden."),
                        { type: "warning" }
                    );
                    return -1;
                }
            }
        }


        if (order) {
            const refPrefix = "Ref. Pago: ";
            let lines = (order.general_note || "").split("\n");
            // Remove previous references to prevent duplicate / stale entries if user goes back
            lines = lines.filter(line => !line.trim().startsWith(refPrefix));
            const cleanRef = (order.payment_reference || "").trim();
            if (cleanRef) {
                lines.push(`${refPrefix}${cleanRef}`);
            }
            order.general_note = lines.join("\n").trim();
        }

        await super.validateOrder(isForceValidate);
    }
});
