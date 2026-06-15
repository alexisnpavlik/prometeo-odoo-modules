/** @odoo-module **/

import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { surchargeMultiplier, surchargedUnitPrice } from "@card_installment/js/installment_math";

export class InfoPopup extends Component {
    static template = "pos_custom_popup.InfoPopup";
    static components = { Dialog };

    setup() {
        this.pos = usePos();
        this.notification = useService("notification");

        this.state = useState({
            installments: this.props.installments || [],
            selected_installment: null,
        });
    }

    chooseInstallment(event) {
        const selectedId = parseInt(event.target.value);
        this.state.selected_installment = this.props.installments.find(
            (inst) => inst.id === selectedId
        );
    }

    confirm() {
        const value = this.state.selected_installment;
        if (!value) {
            this.notification.add(_t("Seleccione una cuota"), { type: "warning" });
            return;
        }

        const order = this.env.services.pos.get_order();
        const paymentline = this.props.paymentline; // línea de pago base de la tarjeta
        const paymentMethod = paymentline.payment_method_id;
        const lines = order.get_orderlines();

        order.is_applying_installment = true;
        try {
            // 1) Quitar una posible línea de recargo previa para no duplicar
            const existingInstallmentLine = (order.payment_ids || []).find(
                (pl) => pl.is_installment && pl.payment_method_id?.id === paymentMethod.id
            );
            if (existingInstallmentLine) {
                order.remove_paymentline(existingInstallmentLine);
            }

            // 2) Restaurar precios originales antes de recalcular (idempotente al re-elegir plan)
            lines.forEach((line) => {
                if (line.original_unit_price !== undefined) {
                    line.set_unit_price(line.original_unit_price);
                }
            });

            // 3) Total neto (ya con descuentos de línea e impuestos, sin recargo)
            const net_total = order.get_total_with_tax();

            // 4) Multiplicador combinado: recargo financiero y reintegro
            const multiplier = surchargeMultiplier(value.coefficient, value.bank_discount);

            // Total objetivo: lo que mostró el popup (server) o, si faltara, neto * multiplicador
            const target_total =
                value.final_amount !== undefined && value.final_amount !== null
                    ? value.final_amount
                    : net_total * multiplier;

            // Cantidad de cuotas a informar
            const installment_qty = value.installment || value.divisor || 1;
            paymentline.selected_installment_qty = installment_qty;

            // 5) Aplicar el recargo/descuento de forma proporcional por línea.
            //    Escalar el precio unitario conserva descuentos y cantidades de cada línea
            //    y deja en 0 las líneas de precio 0 (sin división → sin NaN).
            lines.forEach((line) => {
                if (line.original_unit_price === undefined) {
                    line.original_unit_price = line.get_unit_price();
                }
                line.set_unit_price(surchargedUnitPrice(line.original_unit_price, multiplier));
                // marca usada por la validación de cuotas
                if (line.original_price === undefined) {
                    line.original_price = line.original_unit_price;
                }
            });

            // 6) Ajuste fino por redondeo (la suma de líneas redondeadas puede diferir por centavos)
            const activeLines = lines.filter((l) => l.qty > 0);
            if (activeLines.length > 0 && Math.abs(order.get_total_with_tax() - target_total) > 0.001) {
                const lastLine = activeLines[activeLines.length - 1];
                let iterations = 0;
                let prev_total = null;
                while (
                    Math.abs(order.get_total_with_tax() - target_total) > 0.001 &&
                    iterations < 100
                ) {
                    const diff = target_total - order.get_total_with_tax();
                    const current_unit_price = lastLine.get_unit_price();
                    const step = diff / lastLine.qty;
                    if (Math.abs(step) < 0.0001) {
                        break;
                    }
                    lastLine.set_unit_price(current_unit_price + step);
                    let new_total = order.get_total_with_tax();
                    if (new_total === prev_total) {
                        // Sin cambio por redondeo estricto: forzar un paso de 1 centavo
                        lastLine.set_unit_price(current_unit_price + (diff > 0 ? 0.01 : -0.01));
                        new_total = order.get_total_with_tax();
                        if (new_total === prev_total) {
                            break;
                        }
                    }
                    prev_total = new_total;
                    iterations++;
                }
            }

            // 7) Línea de pago que representa el recargo financiero (diferencia con los otros pagos).
            //    Se ajusta para que la suma de pagos coincida exactamente con el total.
            const surcharge = target_total - net_total;
            if (Math.abs(surcharge) > 0.001) {
                const newPaymentLine = order.add_paymentline(paymentMethod);
                if (newPaymentLine) {
                    newPaymentLine.is_installment = true;
                    newPaymentLine.installment_qty = installment_qty;
                    newPaymentLine.installment_name = _t("Recargo por %s cuotas", installment_qty);

                    const otherPaymentsSum = (order.payment_ids || [])
                        .filter((pl) => pl !== newPaymentLine)
                        .reduce((sum, pl) => sum + pl.amount, 0);
                    newPaymentLine.set_amount(order.get_total_with_tax() - otherPaymentsSum);
                }
            }
        } finally {
            delete order.is_applying_installment;
        }

        this.props.getPayload({ installment: value });
        this.props.close();
    }
}
