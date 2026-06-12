/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Component, useState } from "@odoo/owl";

export class InfoPopup extends Component {
    static template = "pos_custom_popup.InfoPopup";
    static components = { Dialog };

    setup() {
        this.pos = usePos();

        this.state = useState({
            installments: this.props.installments || [],
            selected_installment: null,
        });
    }

    chooseInstallment(event) {
        let selectedId = parseInt(event.target.value);
        console.log("Installment selected:", selectedId);
        let selectedObject = this.props.installments.find(
            (inst) => inst.id === selectedId
        );
        console.log("Installment selected:", selectedObject);
        this.state.selected_installment = selectedObject;
    }

    confirm() {

        debugger;

        if (!this.state.selected_installment) {
            alert("Seleccione una cuota");
            return -1;
        }

        //console.log("Confirming with installment:", this.state.selected_installment);

        const installmentsall = this.props.allInstallments;
        const order = this.env.services.pos.get_order();
        const paymentline = this.props.paymentline; // solo para obtener el método
        const paymentMethod = paymentline.payment_method_id;

        const lines = order.get_orderlines();

        // 🔹 Si ya existe una línea de pago de recargo/cuota previa, la eliminamos para no duplicar
        const existingInstallmentLine = (order.payment_ids || []).find(
            (pl) => pl.is_installment && pl.payment_method_id?.id === paymentMethod.id
        );
        if (existingInstallmentLine) {
            console.log("🗑️ Eliminando línea de recargo previa antes de aplicar la nueva:", existingInstallmentLine);
            order.remove_paymentline(existingInstallmentLine);
        }

        // 🔹 Guardar información de las cuotas en la línea de pago base de la tarjeta (propiedad no-imprimible)
        const installment_qty = this.state.selected_installment.installment || this.state.selected_installment.divisor || 1;
        if (paymentline) {
            paymentline.selected_installment_qty = installment_qty;
        }

        //console.log("lines ", lines)
        //console.log("lines quantity", lines.length)
        let counter = 0
        let totalQty = 0

        lines.forEach(lineI => {totalQty += lineI.qty});

        console.log("Amount total:", totalQty);

        const original_order_total = order.get_total_with_tax();
        const value = this.state.selected_installment;
        const target_order_total = original_order_total + parseFloat(value.fee);
        let installmentPaymentLine = null;

        lines.forEach(lineI => {

            const value_origin = installmentsall[lineI.id][paymentMethod.card_id]
                .installments
                .find(inst => inst.id === this.state.selected_installment.id);

            if (!value) {
                return;
            }

            console.log("installment ", value_origin)

            var coef = value_origin.base_amount / (value_origin.base_amount * (totalQty));

            console.log("coef ", coef)
            console.log("value base amount ", value.base_amount)
            console.log("value_origin base amount ", value_origin.base_amount)

            if(value.base_amount < order.amount_total)
            {
                var fee_prop = parseFloat(value.fee) * coef;
            }
            else
            {
                var fee_prop = (value_origin.coefficient - 1) * value_origin.base_amount;
            }


            const amount = parseFloat(value.fee) //* lineI.qty;

            //console.log("Adding payment line amount:", amount);

            // 🔹 Crear una nueva línea de pago
            if(amount > 0 && counter < 1)
            {
                const newPaymentLine = order.add_paymentline(paymentMethod);

                if (newPaymentLine) {
                    newPaymentLine.set_amount(amount);
                    newPaymentLine.is_installment = true;
                    console.log("🔍 installment_qty final:", installment_qty);
                    newPaymentLine.installment_qty = installment_qty;
                    newPaymentLine.installment_name = `Recargo por ${installment_qty} cuotas`;
                    installmentPaymentLine = newPaymentLine;
                }
            }
            
            // Guardar el precio original antes de modificarlo
            if (!lineI.original_unit_price) {
                lineI.original_unit_price = lineI.get_unit_price();
            }
            // ajustar el precio unitario con el recargo de cuotas
            lineI.set_unit_price(value_origin.base_amount + fee_prop);

            // Re-establecer lineI.original_price para que pase la validación de cuotas
            if (!lineI.original_price) {
                lineI.original_price = lineI.original_unit_price;
            }

            counter++;
            
        });

        // 🔹 Ajustar diferencia por redondeo
        const activeLines = lines.filter(l => l.qty > 0);
        if (activeLines.length > 0) {
            const lastLine = activeLines[activeLines.length - 1];
            let iterations = 0;
            const maxIterations = 100;
            let prev_total = order.get_total_with_tax();

            while (Math.abs(order.get_total_with_tax() - target_order_total) > 0.001 && iterations < maxIterations) {
                let diff = target_order_total - order.get_total_with_tax();
                let current_unit_price = lastLine.get_unit_price();
                
                let step = diff / lastLine.qty;
                if (Math.abs(step) < 0.0001) {
                    break;
                }
                
                lastLine.set_unit_price(current_unit_price + step);
                
                let new_total = order.get_total_with_tax();
                if (new_total === prev_total) {
                    // Si no hubo cambio (debido a redondeo estricto), forzar un paso de 0.01
                    lastLine.set_unit_price(current_unit_price + (diff > 0 ? 0.01 : -0.01));
                    new_total = order.get_total_with_tax();
                    if (new_total === prev_total) {
                        break;
                    }
                }
                prev_total = new_total;
                iterations++;
            }
            console.log(`🔧 Ajuste por redondeo completado en ${iterations} iteraciones. Total final:`, order.get_total_with_tax());
        }

        // 🔹 Ajustar diferencia final en la línea de pago de recargo/cuotas para coincidir perfectamente
        if (installmentPaymentLine) {
            const allPaymentLines = order.payment_ids || [];
            let otherPaymentsSum = 0;
            allPaymentLines.forEach(pl => {
                if (pl !== installmentPaymentLine) {
                    otherPaymentsSum += pl.amount;
                }
            });
            
            const final_surcharge_amount = order.get_total_with_tax() - otherPaymentsSum;
            console.log("🔧 Ajustando línea de recargo de:", installmentPaymentLine.amount, "a:", final_surcharge_amount);
            installmentPaymentLine.set_amount(final_surcharge_amount);
        }

        this.props.getPayload({
            installment: this.state.selected_installment,
        });

        this.props.close();
    }
}
