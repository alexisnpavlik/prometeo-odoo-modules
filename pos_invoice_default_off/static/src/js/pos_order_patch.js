import { patch } from "@web/core/utils/patch";
import { PosOrder } from "@point_of_sale/app/models/pos_order";

patch(PosOrder.prototype, {
    set_partner(partner) {
        const previous = this.to_invoice;
        super.set_partner(partner);
        this.to_invoice = previous;
    },
});
