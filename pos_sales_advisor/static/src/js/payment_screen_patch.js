/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { SelectionPopup } from "@point_of_sale/app/utils/input_popups/selection_popup";
import { makeAwaitable } from "@point_of_sale/app/store/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {
    /**
     * Asesor seleccionado en la orden actual (registro del data-layer o null).
     */
    get currentOrderAdvisor() {
        return this.currentOrder?.sales_advisor_id || null;
    },

    /**
     * Abre el popup de selección de asesor. "Quitar asesor" limpia la selección;
     * cancelar el popup no modifica nada.
     */
    async onClickSalesAdvisor() {
        const advisors = this.pos.models["pos.sales.advisor"].getAll();
        const list = advisors.map((advisor) => ({
            id: advisor.id,
            label: advisor.name,
            isSelected: this.currentOrderAdvisor?.id === advisor.id,
            item: advisor,
        }));
        if (this.currentOrderAdvisor) {
            list.push({ id: 0, label: _t("Quitar asesor"), isSelected: false, item: false });
        }
        const selected = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Seleccionar asesor de venta"),
            list: list,
        });
        if (selected === undefined) {
            return;
        }
        this.currentOrder.update({ sales_advisor_id: selected || false });
    },

    /**
     * Bloquea la validación si la caja requiere asesor y la orden no tiene uno.
     */
    async _isOrderValid(isForceValidate) {
        if (this.pos.config.require_sales_advisor && !this.currentOrderAdvisor) {
            this.dialog.add(AlertDialog, {
                title: _t("Falta el asesor de venta"),
                body: _t("Esta caja requiere seleccionar un asesor de venta antes de validar el pago."),
            });
            return false;
        }
        return super._isOrderValid(isForceValidate);
    },
});
