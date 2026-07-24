/** @odoo-module **/

import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(ClosePosPopup.prototype, {
    /**
     * Bloquea el cierre de caja si quedan órdenes con productos sin finalizar.
     * Cubre cualquier orden en memoria (sincronizada o no), no solo las que el
     * flujo base marca como draft server-side. El cajero debe cobrarlas o
     * cancelarlas (el borrado pide motivo) antes de poder cerrar.
     */
    async confirm() {
        if (this.pos.config.block_close_with_pending_orders) {
            const pending = this.pos.models["pos.order"].filter(
                (o) => !o.finalized && o.get_orderlines().length > 0
            );
            if (pending.length) {
                const refs = pending
                    .map((o) => o.pos_reference || o.name || o.uuid)
                    .join(", ");
                this.dialog.add(AlertDialog, {
                    title: _t("No se puede cerrar la caja"),
                    body: _t(
                        "Hay %s orden(es) con productos sin finalizar (%s). " +
                            "Cobralas o cancelalas (se pedirá motivo) antes de cerrar la caja.",
                        pending.length,
                        refs
                    ),
                });
                return;
            }
        }
        return super.confirm(...arguments);
    },
});
