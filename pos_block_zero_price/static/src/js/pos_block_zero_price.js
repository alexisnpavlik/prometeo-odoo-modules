/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PosOrder.prototype, {
    /** Líneas de venta con precio unitario $0 (sin devoluciones ni líneas de combo). */
    getZeroPriceLines() {
        return this.get_orderlines().filter(
            (line) =>
                line.get_quantity() > 0 &&
                !line.combo_parent_id &&
                !line.combo_line_ids?.length &&
                roundCurrency(line.get_unit_price(), line.currency) === 0
        );
    },
});

/** Avisa qué productos están a $0; devuelve true si la orden se puede cobrar. */
function checkZeroPrice(pos, order) {
    const lines = order?.getZeroPriceLines() || [];
    if (!lines.length) {
        return true;
    }
    const names = lines.map((line) => `• ${line.get_full_product_name()}`).join("\n");
    pos.dialog.add(AlertDialog, {
        title: _t("Productos con precio $0"),
        body: _t("No se puede cobrar: estos productos están a $0.\n%s\n\nCorregí el precio o quitalos de la orden.", names),
    });
    return false;
}

patch(PosStore.prototype, {
    /** Frena el paso a Pago si hay productos a $0. */
    async pay() {
        if (!checkZeroPrice(this, this.get_order())) {
            return;
        }
        return super.pay(...arguments);
    },
});

patch(PaymentScreen.prototype, {
    /** Segundo control al validar, por si la orden cambió en la pantalla de pago. */
    async validateOrder(isForceValidate) {
        if (!checkZeroPrice(this.pos, this.currentOrder)) {
            return;
        }
        return super.validateOrder(...arguments);
    },
});
