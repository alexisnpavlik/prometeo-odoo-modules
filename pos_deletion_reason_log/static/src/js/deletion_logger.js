/** @odoo-module **/

import { DeletionReasonPopup } from "./deletion_reason_popup";

/**
 * Muestra el popup de motivo. Devuelve {reason_id, reason_note} o null si se canceló.
 */
export async function askReason(component, title) {
    const dialog = component.env.services.dialog;
    return new Promise((resolve) => {
        dialog.add(DeletionReasonPopup, {
            title: title,
            getPayload: (result) => resolve(result),
            close: () => resolve(null),
        });
    });
}

/**
 * Registra la eliminación en el backend (best-effort; no traba el POS si falla).
 */
export async function logDeletion(component, vals) {
    try {
        const pos = component.env.services.pos;
        const orm = component.env.services.orm;
        const fullVals = {
            pos_config_id: pos.config.id,
            session_id: pos.session.id,
            ...vals,
        };
        await orm.call("pos.deletion.log", "log_deletion", [fullVals]);
    } catch (error) {
        console.error("pos_deletion_reason_log: no se pudo registrar la eliminación", error);
    }
}

/**
 * Snapshot de una orden para el registro (tolerante a orden vacía).
 */
export function snapshotOrder(order) {
    const lines = (order.get_orderlines && order.get_orderlines()) || [];
    let amount = 0;
    try {
        amount = order.get_total_with_tax ? order.get_total_with_tax() : 0;
    } catch (e) {
        amount = 0;
    }
    return {
        order_ref: order.uuid || order.name || "",
        product_id: lines.length === 1 && lines[0].get_product() ? lines[0].get_product().id : false,
        qty_removed: lines.reduce((s, l) => s + (l.get_quantity ? l.get_quantity() : 0), 0),
        amount_removed: amount,
    };
}
