/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logDeletion } from "./deletion_logger";

patch(OrderSummary.prototype, {
    /**
     * Intercepta borrado de línea ('remove') y reducción de cantidad para pedir motivo.
     */
    async _setValue(val) {
        const order = this.currentOrder;
        const line = order && order.get_selected_orderline && order.get_selected_orderline();
        const config = this.pos.config;

        // Caso 1: eliminación de línea completa
        if (line && val === "remove" && config.require_reason_line_deletion) {
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
                    qty_removed: line.__prevQty != null ? line.__prevQty : (line.get_quantity ? line.get_quantity() : 0),
                    amount_removed: 0,
                    reason_id: reason.reason_id,
                    reason_note: reason.reason_note,
                });
            }
            return result;
        }

        // Caso 2: reducción de cantidad (valor numérico menor al actual)
        if (line && config.require_reason_qty_reduction && this._isNumericValue(val)) {
            const currentQty = line.get_quantity ? line.get_quantity() : 0;
            const newQty = parseFloat(val);
            if (!isNaN(newQty) && newQty < currentQty) {
                const product = line.get_product();
                const reason = await askReason(this, _t("Motivo — Reducir cantidad"));
                if (!reason) {
                    return; // cancelado
                }
                const result = await super._setValue(val);
                await logDeletion(this, {
                    deletion_type: "qty_reduction",
                    order_ref: order.uuid || order.name || "",
                    product_id: product ? product.id : false,
                    qty_removed: currentQty - newQty,
                    amount_removed: 0,
                    reason_id: reason.reason_id,
                    reason_note: reason.reason_note,
                });
                return result;
            }
        }

        return super._setValue(val);
    },

    /**
     * Detecta si el valor del numpad representa una cantidad numérica directa.
     */
    _isNumericValue(val) {
        return typeof val === "string" && /^[0-9]+([.,][0-9]*)?$/.test(val);
    },
});
