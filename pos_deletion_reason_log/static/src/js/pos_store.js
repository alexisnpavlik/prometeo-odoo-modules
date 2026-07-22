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

    /**
     * Antes de cambiar la línea seleccionada, resuelve en background cualquier
     * reducción de cantidad pendiente de motivo sobre la línea que se deja de
     * editar (no se espera esa resolución para no romper el código base, que
     * en varios lugares llama a selectOrderLine sin await). Luego captura la
     * cantidad "de partida" de la nueva línea seleccionada.
     *
     * Se intercepta acá y no en OrderSummary._setValue porque el numpad dispara
     * _setValue en cada tecla (valor intermedio mientras se escribe), y pedir
     * el motivo ahí interrumpe al cajero a mitad de tipeo con datos falsos.
     * selectOrderLine es el único punto por el que pasan tanto el click manual
     * en una línea como el auto-select al agregar/mergear productos.
     */
    selectOrderLine(order, line) {
        this._resolvePendingQtyReduction(order);
        super.selectOrderLine(order, line);
        this._captureQtyBeforeEdit(line);
    },

    /**
     * Guarda la cantidad de la línea en el momento en que se selecciona, para
     * poder comparar contra la cantidad final cuando se deseleccione.
     */
    _captureQtyBeforeEdit(line) {
        if (!line) {
            return;
        }
        if (!this._deletionReasonQtyBeforeEdit) {
            this._deletionReasonQtyBeforeEdit = new Map();
        }
        this._deletionReasonQtyBeforeEdit.set(line.uuid, line.get_quantity());
    },

    /**
     * Si la línea que estaba seleccionada bajó de cantidad respecto a cuando
     * se seleccionó, pide motivo y registra. Si el cajero cancela, revierte la
     * cantidad a la que tenía antes de editar (acá el motivo se pide DESPUÉS
     * del cambio, no antes, a diferencia de los otros flujos — ver nota en
     * selectOrderLine).
     */
    async _resolvePendingQtyReduction(order) {
        if (!order || !this.config.require_reason_qty_reduction || !this._deletionReasonQtyBeforeEdit) {
            return;
        }
        const line = order.get_selected_orderline && order.get_selected_orderline();
        if (!line) {
            return;
        }
        const before = this._deletionReasonQtyBeforeEdit.get(line.uuid);
        this._deletionReasonQtyBeforeEdit.delete(line.uuid);
        if (before == null) {
            return;
        }
        const currentQty = line.get_quantity ? line.get_quantity() : 0;
        if (currentQty >= before) {
            return; // no hubo reducción
        }
        const product = line.get_product();
        const reason = await askReason(this, _t("Motivo — Reducir cantidad"));
        if (!reason) {
            // Cancelado: revertir la cantidad a la que tenía antes de editar
            line.set_quantity(before, Boolean(line.combo_line_ids?.length));
            return;
        }
        await logDeletion(this, {
            deletion_type: "qty_reduction",
            order_ref: order.uuid || order.name || "",
            product_id: product ? product.id : false,
            qty_removed: before - currentQty,
            amount_removed: 0,
            reason_id: reason.reason_id,
            reason_note: reason.reason_note,
        });
    },
});
