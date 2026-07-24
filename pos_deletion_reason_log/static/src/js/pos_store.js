/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { askReason, logEvent, snapshotOrder } from "./control_logger";

patch(PosStore.prototype, {
    /**
     * Bloquea el paso a la pantalla de pago si alguna línea tiene precio
     * unitario 0 (producto sin precio cargado). Se excluyen los hijos de combo,
     * que legítimamente van en 0 porque el precio lo lleva la línea padre.
     */
    async pay() {
        if (this.config.block_zero_price_payment) {
            const order = this.get_order();
            const zeroLines = (order?.get_orderlines() || []).filter(
                (line) =>
                    !line.combo_parent_id &&
                    !line.is_reward_line &&
                    line.get_unit_price() === 0
            );
            if (zeroLines.length) {
                const names = zeroLines
                    .map((l) => l.get_full_product_name?.() || l.get_product()?.display_name || "")
                    .filter(Boolean)
                    .join(", ");
                this.env.services.dialog.add(AlertDialog, {
                    title: _t("No se puede cobrar"),
                    body: _t(
                        "Hay %s producto(s) con precio 0 en la orden (%s). " +
                            "Cargá el precio correcto antes de cobrar.",
                        zeroLines.length,
                        names
                    ),
                });
                return;
            }
        }
        return super.pay(...arguments);
    },

    /**
     * Único choke point de eliminación de órdenes en el POS: tanto el ícono de
     * tacho (onDeleteOrder llama a this.deleteOrders([order]) internamente)
     * como "Cancelar órdenes" del popup de cierre de caja (cuando queda una
     * orden sin finalizar) pasan por acá. Se pide un solo motivo para todo el
     * lote antes de ejecutar la baja real.
     *
     * orders=[] con solo serverIds (sync en background de bajas ya decididas
     * en otro lado) no pide motivo: no hay nada nuevo que el cajero esté
     * decidiendo en este momento.
     */
    async deleteOrders(orders, serverIds = []) {
        if (!this.config.require_reason_order_deletion || !orders || !orders.length) {
            return super.deleteOrders(orders, serverIds);
        }
        const snapshots = orders.map((order) => ({ order, snapshot: snapshotOrder(order) }));
        const title =
            orders.length > 1
                ? _t("Motivo — Cancelar %s órdenes sin finalizar", orders.length)
                : _t("Motivo — Eliminar orden");
        const reason = await askReason(this, title);
        if (!reason) {
            return false; // cancelado: no se elimina ninguna orden del lote
        }
        const result = await super.deleteOrders(orders, serverIds);
        if (result) {
            for (const { order, snapshot } of snapshots) {
                const stillExists = this.data.models["pos.order"].get(order.id);
                if (!stillExists) {
                    await logEvent(this, {
                        event_type: "order",
                        ...snapshot,
                        reason_id: reason.reason_id,
                        reason_note: reason.reason_note,
                    });
                }
            }
        }
        return result;
    },

    /**
     * Antes de cambiar la línea seleccionada, resuelve en background cualquier
     * cambio pendiente de motivo sobre la línea que se deja de editar (cantidad
     * reducida, descuento por encima del umbral, o precio bajado). No se espera
     * esa resolución para no romper el código base, que en varios lugares llama
     * a selectOrderLine sin await. Luego captura el estado "de partida" (cantidad,
     * descuento, precio) de la nueva línea seleccionada.
     *
     * Se intercepta acá y no en OrderSummary._setValue porque el numpad dispara
     * _setValue en cada tecla (valor intermedio mientras se escribe), y pedir
     * el motivo ahí interrumpe al cajero a mitad de tipeo con datos falsos.
     * selectOrderLine es el único punto por el que pasan tanto el click manual
     * en una línea como el auto-select al agregar/mergear productos.
     */
    selectOrderLine(order, line) {
        this._resolvePendingLineChanges(order);
        super.selectOrderLine(order, line);
        this._captureLineBaseline(line);
    },

    /**
     * Guarda cantidad, descuento y precio de la línea en el momento en que se
     * selecciona, para poder comparar contra los valores finales cuando se
     * deseleccione.
     */
    _captureLineBaseline(line) {
        if (!line) {
            return;
        }
        if (!this._controlLogBaseline) {
            this._controlLogBaseline = new Map();
        }
        this._controlLogBaseline.set(line.uuid, {
            qty: line.get_quantity(),
            discount: line.get_discount(),
            price: line.get_unit_price(),
        });
    },

    /**
     * Compara el estado final de la línea que estaba seleccionada contra su
     * baseline y, si corresponde, pide motivo para cada cambio detectado
     * (cantidad reducida, descuento alto, precio bajado). Si el cajero cancela
     * el motivo de un cambio, ese cambio puntual se revierte (acá el motivo se
     * pide DESPUÉS del cambio, no antes, a diferencia del flujo de eliminación).
     */
    async _resolvePendingLineChanges(order) {
        if (!order || !this._controlLogBaseline) {
            return;
        }
        const line = order.get_selected_orderline && order.get_selected_orderline();
        if (!line) {
            return;
        }
        const before = this._controlLogBaseline.get(line.uuid);
        this._controlLogBaseline.delete(line.uuid);
        if (!before) {
            return;
        }

        await this._resolveQtyReduction(order, line, before);
        await this._resolveHighDiscount(order, line, before);
        await this._resolvePriceReduction(order, line, before);
    },

    async _resolveQtyReduction(order, line, before) {
        if (!this.config.require_reason_qty_reduction) {
            return;
        }
        const currentQty = line.get_quantity ? line.get_quantity() : 0;
        if (currentQty >= before.qty) {
            return;
        }
        const product = line.get_product();
        const reason = await askReason(this, _t("Motivo — Reducir cantidad"));
        if (!reason) {
            line.set_quantity(before.qty, Boolean(line.combo_line_ids?.length));
            return;
        }
        await logEvent(this, {
            event_type: "qty_reduction",
            order_ref: order.uuid || order.name || "",
            product_id: product ? product.id : false,
            qty_removed: before.qty - currentQty,
            amount_removed: 0,
            reason_id: reason.reason_id,
            reason_note: reason.reason_note,
        });
    },

    async _resolveHighDiscount(order, line, before) {
        if (!this.config.require_reason_high_discount) {
            return;
        }
        const threshold = this.config.high_discount_threshold || 0;
        const currentDiscount = line.get_discount ? line.get_discount() : 0;
        if (currentDiscount <= threshold || currentDiscount <= before.discount) {
            return; // no subió por encima del umbral en esta edición
        }
        const product = line.get_product();
        const reason = await askReason(this, _t("Motivo — Descuento alto"));
        if (!reason) {
            line.set_discount(before.discount);
            return;
        }
        const qty = line.get_quantity ? line.get_quantity() : 0;
        const price = line.get_unit_price ? line.get_unit_price() : 0;
        await logEvent(this, {
            event_type: "high_discount",
            order_ref: order.uuid || order.name || "",
            product_id: product ? product.id : false,
            discount_percent: currentDiscount,
            amount_removed: price * qty * (currentDiscount / 100),
            reason_id: reason.reason_id,
            reason_note: reason.reason_note,
        });
    },

    async _resolvePriceReduction(order, line, before) {
        if (!this.config.require_reason_price_reduction) {
            return;
        }
        const currentPrice = line.get_unit_price ? line.get_unit_price() : 0;
        if (currentPrice >= before.price) {
            return;
        }
        const product = line.get_product();
        const reason = await askReason(this, _t("Motivo — Reducir precio"));
        if (!reason) {
            line.set_unit_price(before.price);
            return;
        }
        const qty = line.get_quantity ? line.get_quantity() : 0;
        await logEvent(this, {
            event_type: "price_reduction",
            order_ref: order.uuid || order.name || "",
            product_id: product ? product.id : false,
            old_price: before.price,
            new_price: currentPrice,
            amount_removed: (before.price - currentPrice) * qty,
            reason_id: reason.reason_id,
            reason_note: reason.reason_note,
        });
    },
});
