/** @odoo-module **/

import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { askReason, logEvent } from "./control_logger";

patch(ControlButtons.prototype, {
    /**
     * Descuento global (pos_discount). No pasa por el control por línea: en vez
     * de tocar line.discount, agrega una línea con el producto de descuento y
     * precio negativo, así que get_discount() nunca lo ve.
     *
     * Acá el porcentaje llega explícito como argumento, así que se pide el
     * motivo ANTES de aplicar (ask-before) y no hace falta revertir nada si el
     * cajero cancela: simplemente no se aplica el descuento.
     *
     * IMPORTANTE: pos_discount implementa apply_discount sin llamar a super, así
     * que este patch solo funciona si nuestro asset carga después del suyo — de
     * ahí la dependencia explícita a pos_discount en el manifest.
     */
    async apply_discount(pc) {
        const pos = this.pos;
        const threshold = pos.config.high_discount_threshold || 0;
        if (!pos.config.require_reason_high_discount || !(pc > threshold)) {
            return super.apply_discount(...arguments);
        }

        const reason = await askReason(
            this,
            `${_t("Motivo — Descuento global")} ${pc}%`
        );
        if (!reason) {
            return; // cancelado: el descuento no se aplica
        }

        const order = pos.get_order();
        const res = await super.apply_discount(...arguments);

        // El importe descontado son las líneas del producto de descuento que
        // acaba de agregar el super (precio negativo, de ahí el Math.abs).
        const discountProduct = pos.config.discount_product_id;
        const amount = (order?.get_orderlines() || [])
            .filter((line) => line.get_product() === discountProduct)
            .reduce((sum, line) => sum + Math.abs(line.get_price_with_tax?.() || 0), 0);

        await logEvent(this, {
            event_type: "high_discount",
            order_ref: order?.uuid || order?.name || "",
            discount_percent: pc,
            amount_removed: amount,
            reason_id: reason.reason_id,
            reason_note: reason.reason_note,
        });
        return res;
    },
});
