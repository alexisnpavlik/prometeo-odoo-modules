/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype, {
    /**
     * La orden de devolución hereda el asesor de la orden original.
     */
    async addAdditionalRefundInfo(order, destinationOrder) {
        if (order.sales_advisor_id) {
            destinationOrder.update({ sales_advisor_id: order.sales_advisor_id });
        }
        return super.addAdditionalRefundInfo(order, destinationOrder);
    },
});
