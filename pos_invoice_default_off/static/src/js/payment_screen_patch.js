import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";

patch(PaymentScreen.prototype, {
    onMounted() {
        super.onMounted();
        if (this.currentOrder && !this.currentOrder.finalized) {
            this.currentOrder.to_invoice = false;
        }
    },
});
