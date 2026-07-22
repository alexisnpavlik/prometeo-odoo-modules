/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logDeletion, snapshotOrder } from "./deletion_logger";

patch(PosStore.prototype, {
    /**
     * Pide motivo antes de eliminar la orden y registra si la eliminación ocurrió.
     */
    async onDeleteOrder(order) {
        if (!this.config.require_reason_order_deletion) {
            return super.onDeleteOrder(order);
        }
        const snapshot = snapshotOrder(order);
        const reason = await askReason(this, _t("Motivo — Eliminar orden"));
        if (!reason) {
            return false; // cancelado: no eliminar
        }
        const result = await super.onDeleteOrder(order);
        // Verificar que la orden ya no exista en el POS
        const stillExists = this.data.models["pos.order"].get(order.id);
        if (!stillExists) {
            await logDeletion(this, {
                deletion_type: "order",
                ...snapshot,
                reason_id: reason.reason_id,
                reason_note: reason.reason_note,
            });
        }
        return result;
    },
});
