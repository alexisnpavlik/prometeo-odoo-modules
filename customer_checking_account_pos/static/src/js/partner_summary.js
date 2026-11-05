/** @odoo-module **/

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { getCcaPaymentProductId } from "@customer_checking_account_pos/js/pos_order";

/** Pide al servidor el saldo de cuenta corriente del cliente; null si no se pudo (offline). */
export async function fetchCcaPartnerSummary(pos, partner) {
    if (!partner?.id) {
        return null;
    }
    try {
        return await pos.data.call("res.partner", "cca_pos_partner_summary", [
            partner.id,
            pos.company.id,
        ]);
    } catch (error) {
        console.warn("cca: no se pudo leer la cuenta corriente del cliente", error);
        return null;
    }
}

/** Texto corto con saldo y vencido para notificaciones. */
export function formatCcaSummary(pos, summary) {
    if (!summary) {
        return _t("No se pudo consultar la cuenta corriente.");
    }
    if (!summary.has_account) {
        return _t("El cliente no tiene cuenta corriente.");
    }
    const fmt = (value) => pos.env.utils.formatCurrency(value);
    return _t("Saldo: %(balance)s · Vencido: %(overdue)s", {
        balance: fmt(summary.balance),
        overdue: fmt(summary.overdue),
    });
}

patch(PosStore.prototype, {
    /** Al agregar el producto de pago con cliente elegido, avisa saldo y vencido. */
    async addLineToOrder(vals, order, opts = {}, configure = true) {
        const result = await super.addLineToOrder(...arguments);
        const productId = getCcaPaymentProductId(this.config);
        const product = vals?.product_id;
        const addedId = typeof product === "object" ? product?.id : product;
        const partner = order?.get_partner();
        if (productId && addedId === productId && partner) {
            fetchCcaPartnerSummary(this, partner).then((summary) => {
                this.notification.add(formatCcaSummary(this, summary), {
                    title: _t("Cuenta corriente de %s", partner.name),
                    type: summary?.overdue > 0 ? "warning" : "info",
                });
            });
        }
        return result;
    },
});
