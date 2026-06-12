/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

patch(PosOrder.prototype, {
    export_for_printing(baseUrl, headerData) {
        const result = super.export_for_printing(baseUrl, headerData);
        
        // Remove the payment reference from the ticket general notes
        if (result && typeof result.generalNote === "string") {
            const refPrefix = "Ref. Pago: ";
            let lines = result.generalNote.split("\n");
            lines = lines.filter(line => !line.trim().startsWith(refPrefix));
            result.generalNote = lines.join("\n").trim();
        }
        
        return result;
    },

    remove_paymentline(paymentline) {
        console.log("🗑️ remove_paymentline en PosOrder:", paymentline);

        const isCardOrInstallment = paymentline.payment_method_id?.card_id || paymentline.is_installment;

        if (isCardOrInstallment) {
            const lines = this.get_orderlines();

            // Restaurar el precio original del producto si fue modificado por cuotas
            lines.forEach(lineI => {
                if (lineI.original_unit_price) {
                    lineI.set_unit_price(lineI.original_unit_price);
                    delete lineI.original_unit_price;
                }
                if (lineI.original_price) {
                    delete lineI.original_price;
                }
            });

            // Si se elimina la línea base de la tarjeta (la que no es de recargo),
            // también debemos eliminar la línea de recargo asociada (is_installment)
            if (paymentline.payment_method_id?.card_id && !paymentline.is_installment) {
                const installmentLine = (this.payment_ids || []).find(
                    (pl) => pl.is_installment && pl.payment_method_id?.id === paymentline.payment_method_id?.id
                );
                if (installmentLine) {
                    console.log("🗑️ Eliminando también la línea de recargo asociada desde remove_paymentline:", installmentLine);
                    this.remove_paymentline(installmentLine);
                }
            }

            // Si se elimina la línea de recargo, debemos limpiar el nombre e indicador de la línea base
            if (paymentline.is_installment) {
                const baseLine = (this.payment_ids || []).find(
                    (pl) => pl.payment_method_id?.id === paymentline.payment_method_id?.id && !pl.is_installment
                );
                if (baseLine) {
                    delete baseLine.selected_installment_qty;
                }
            }

            // Si se elimina la línea base directamente, limpiamos su info por buena práctica
            if (paymentline.payment_method_id?.card_id && !paymentline.is_installment) {
                delete paymentline.selected_installment_qty;
            }
        }

        // Limpiar la referencia de pago si ya no quedan líneas de pago con tarjeta (excluyendo la que se elimina y la de recargo)
        const remainingCardLine = (this.payment_ids || []).find(
            (pl) => pl.payment_method_id?.card_id && pl !== paymentline && !pl.is_installment
        );
        if (!remainingCardLine) {
            this.payment_reference = "";
        }

        return super.remove_paymentline(paymentline);
    }
});
