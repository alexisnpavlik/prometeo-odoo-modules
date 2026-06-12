/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";

export const CardInstallmentService = {
    dependencies: ["pos"],
    start(env, { pos }) {
        pos.getInstallments = async function (card_id, amount_total) {
            return await rpc('/pos/installments', {
                card_id: card_id,
                amount_total: amount_total,
            });
        };

        pos.getCardID = async function (payment_method_id) {
            return await rpc('/pos/get_payment_method_card', {
                payment_method_id: payment_method_id,
            });
        }
    },
};

registry.category("services").add("card_installment_service", CardInstallmentService);
