/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logEvent } from "./control_logger";

patch(OrderSummary.prototype, {
    /**
     * Intercepta borrado de línea completa ('remove') y puesta en cero de la
     * cantidad ('') para pedir motivo.
     *
     * El buffer manda val === "" en el primer Suprimir/Backspace sobre una línea
     * recién seleccionada (number_buffer, rama isReset) y val === "remove" en el
     * segundo. Sin interceptar el primero, la línea queda en 0,00 sin pedir nada
     * —visualmente "borrada"— y el motivo recién se pedía al deseleccionarla.
     *
     * El resto de la reducción de cantidad (bajar de 5 a 2, etc.) se resuelve
     * aparte, en PosStore.selectOrderLine (pos_store.js), porque acá _setValue se
     * dispara en cada tecla del numpad y no al confirmar el valor final.
     */
    async _setValue(val) {
        const order = this.currentOrder;
        const line = order && order.get_selected_orderline && order.get_selected_orderline();
        const config = this.pos.config;
        const { numpadMode } = this.pos;

        const askOnZero =
            config.require_reason_line_deletion || config.require_reason_qty_reduction;
        if (
            line &&
            numpadMode === "quantity" &&
            val === "" &&
            askOnZero &&
            (line.get_quantity ? line.get_quantity() : 0) !== 0
        ) {
            const product = line.get_product();
            const qtyBefore = line.get_quantity();
            const reason = await askReason(this, _t("Motivo — Poner cantidad en cero"));
            if (!reason) {
                return; // cancelado: la línea conserva su cantidad
            }
            const result = await super._setValue(val);
            // Evita que _resolveQtyReduction vuelva a pedir motivo por el mismo
            // cambio cuando se deseleccione la línea.
            this.pos._captureLineBaseline(line);
            await logEvent(this, {
                event_type: "qty_reduction",
                order_ref: order.uuid || order.name || "",
                product_id: product ? product.id : false,
                qty_removed: qtyBefore,
                amount_removed: 0,
                reason_id: reason.reason_id,
                reason_note: reason.reason_note,
            });
            return result;
        }

        // Una línea ya en 0 no tiene nada que quitar: su motivo se pidió al
        // ponerla en cero, así que sacarla de la pantalla no vuelve a preguntar.
        if (
            line &&
            numpadMode === "quantity" &&
            val === "remove" &&
            config.require_reason_line_deletion &&
            (line.get_quantity ? line.get_quantity() : 0) !== 0
        ) {
            const product = line.get_product();
            const reason = await askReason(this, _t("Motivo — Eliminar línea"));
            if (!reason) {
                return; // cancelado
            }
            const result = await super._setValue(val);
            const stillExists = order.get_orderlines().includes(line);
            if (!stillExists) {
                await logEvent(this, {
                    event_type: "line",
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

        // Red de seguridad para la reducción por tecleo directo: garantiza que la
        // línea tenga un baseline aunque no se haya seleccionado vía
        // selectOrderLine (p.ej. selección restaurada al abrir/cambiar de orden).
        // Se captura AHORA, antes de que super aplique el cambio, así el valor
        // guardado es el previo a la edición y _resolvePendingLineChanges detecta
        // la reducción al deseleccionar o cobrar.
        if (
            line &&
            val !== "" &&
            val !== "remove" &&
            (!this.pos._controlLogBaseline || !this.pos._controlLogBaseline.has(line.uuid))
        ) {
            this.pos._captureLineBaseline(line);
        }

        return super._setValue(val);
    },

    /**
     * Al deseleccionar una línea clickeándola de nuevo, el core NO pasa por
     * selectOrderLine, así que los cambios pendientes (reducción de cantidad,
     * descuento o precio) nunca se resolvían y no se pedía motivo. Se resuelven
     * acá, antes de perder la selección. (En doble click el core edita lotes, no
     * deselecciona, así que se omite.)
     */
    clickLine(ev, orderline) {
        if (orderline.isSelected() && ev.detail !== 2) {
            this.pos._resolvePendingLineChanges(this.currentOrder);
        }
        return super.clickLine(...arguments);
    },
});
