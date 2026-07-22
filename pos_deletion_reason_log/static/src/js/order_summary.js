/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logDeletion } from "./deletion_logger";

patch(OrderSummary.prototype, {
    /**
     * Intercepta borrado de línea completa ('remove') para pedir motivo.
     * La reducción de cantidad se resuelve aparte, en PosStore.selectOrderLine
     * (pos_store.js), porque acá _setValue se dispara en cada tecla del numpad
     * y no al confirmar el valor final.
     */
    async _setValue(val) {
        const order = this.currentOrder;
        const line = order && order.get_selected_orderline && order.get_selected_orderline();
        const config = this.pos.config;
        const { numpadMode } = this.pos;

        if (line && numpadMode === "quantity" && val === "remove" && config.require_reason_line_deletion) {
            const product = line.get_product();
            const reason = await askReason(this, _t("Motivo — Eliminar línea"));
            if (!reason) {
                return; // cancelado
            }
            const result = await super._setValue(val);
            const stillExists = order.get_orderlines().includes(line);
            if (!stillExists) {
                await logDeletion(this, {
                    deletion_type: "line",
                    order_ref: order.uuid || order.name || "",
                    product_id: product ? product.id : false,
                    qty_removed: line.get_quantity ? line.get_quantity() : 0,
                    amount_removed: 0,
                    reason_id: reason.reason_id,
                    reason_note: reason.reason_note,
                });
            }
            return result;
        }

        return super._setValue(val);
    },
});
