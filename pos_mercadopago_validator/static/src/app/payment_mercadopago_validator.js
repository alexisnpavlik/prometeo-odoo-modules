/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { PaymentInterface } from "@point_of_sale/app/payment/payment_interface";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { MercadoPagoInboxDialog } from "@pos_mercadopago_validator/app/inbox_dialog";

export class PaymentMercadoPagoValidator extends PaymentInterface {
    setup() {
        super.setup(...arguments);
        this.pendingResolver = null;
        // Reserva hecha en el servidor que el cajero todavía no confirmó. Si el
        // cobro se abandona con una reserva viva hay que devolverla a la bandeja:
        // si no, el pago queda en `matched` sin orden, invisible para todas las
        // cajas, y el cajero termina aprobando a mano un cobro que sí entró.
        this.pendingLine = null;
    }

    // El cajero fija el monto antes de que se abra la bandeja.
    get fast_payments() {
        return false;
    }

    async send_payment_request(uuid) {
        await super.send_payment_request(...arguments);
        const line = this.pos.get_order().get_selected_paymentline();
        line.set_payment_status("waitingCard");

        return new Promise((resolve) => {
            this.pendingResolver = resolve;
            this.env.services.dialog.add(
                MercadoPagoInboxDialog,
                {
                    paymentMethod: line.payment_method_id,
                    amount: line.amount,
                    onPicked: async (inboxLine, ambiguous) => {
                        const result = await this._impute(line, inboxLine, ambiguous);
                        if (!result.ok) {
                            this.env.services.dialog.add(AlertDialog, {
                                title: _t("Pago ya asignado"),
                                body: result.error,
                            });
                            return false;
                        }
                        this.pendingLine = line;
                        line.set_receipt_info(_t("Mercado Pago %s", result.mp_payment_id));
                        line.transaction_id = result.mp_payment_id;
                        // Viaja al servidor al sincronizar la orden y convierte la
                        // reserva por uuid en la imputación definitiva.
                        line.mercadopago_uuid = line.uuid;
                        line.set_payment_status("done");
                        return true;
                    },
                    // La imputación automática se confirma o se deshace: hasta que el
                    // cajero decide, la promesa del cobro sigue abierta a propósito.
                    onUndo: async () => {
                        const result = await this._revertReservation(line);
                        if (!result.ok) {
                            this.env.services.dialog.add(AlertDialog, {
                                title: _t("No se pudo deshacer"),
                                body: result.error,
                            });
                            return false;
                        }
                        return true;
                    },
                    onDone: () => {
                        this.pendingLine = null;
                        this._resolve(true);
                    },
                    onManualApproval: async (reason) => {
                        await this.env.services.orm.call(
                            "pos.payment.method",
                            "register_manual_approval",
                            [[line.payment_method_id.id], line.uuid, reason]
                        );
                        line.set_payment_status("done");
                        this.pendingLine = null;
                        this._resolve(true);
                    },
                    onCancel: () => this._abandon(),
                },
                {
                    // Cerrar con Escape o con la X no pasa por onCancel: sin esta red
                    // la promesa del cobro nunca se resuelve, la línea queda colgada
                    // en waitingCard y la reserva sin confirmar se pierde para siempre.
                    onClose: () => this._abandon(),
                }
            );
        });
    }

    async _impute(line, inboxLine, ambiguous) {
        // La línea todavía no existe en el servidor: se imputa por uuid.
        // inboxLine.id es el id interno de Odoo, no el mp_payment_id externo.
        return await this.env.services.orm.silent.call(
            "pos.payment.method",
            "impute_mp_payment_by_uuid",
            [[line.payment_method_id.id], inboxLine.id, line.uuid, ambiguous]
        );
    }

    /**
     * Devuelve la reserva a la bandeja y deja la línea como estaba antes.
     */
    async _revertReservation(line) {
        const result = await this.env.services.orm.silent.call(
            "pos.payment.method",
            "revert_mp_reservation_by_uuid",
            [[line.payment_method_id.id], line.uuid]
        );
        if (!result.ok) {
            return result;
        }
        this.pendingLine = null;
        // set_receipt_info() concatena (`this.ticket += value` en pos_payment.js):
        // limpiar de verdad exige escribir el campo, si no el comprobante sale con
        // la referencia vieja pegada a la nueva.
        line.update({ ticket: "" });
        line.transaction_id = false;
        line.mercadopago_uuid = false;
        line.set_payment_status("waitingCard");
        return result;
    }

    /**
     * Abandona el cobro liberando la reserva que el cajero nunca confirmó.
     */
    async _abandon() {
        const line = this.pendingLine;
        if (line) {
            this.pendingLine = null;
            try {
                await this._revertReservation(line);
            } catch (error) {
                // El cobro se abandona igual: dejar la promesa sin resolver es peor
                // que una reserva colgada, que el backoffice todavía puede revertir.
                console.warn("No se pudo liberar la reserva de Mercado Pago", error);
            }
        }
        this._resolve(false);
    }

    _resolve(value) {
        this.pendingResolver?.(value);
        this.pendingResolver = null;
    }

    async send_payment_cancel(order, uuid) {
        await super.send_payment_cancel(order, uuid);
        await this._abandon();
        return true;
    }

    close() {
        super.close();
        this._abandon();
    }
}
