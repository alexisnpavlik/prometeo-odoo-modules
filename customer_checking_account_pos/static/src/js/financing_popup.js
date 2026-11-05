/** @odoo-module **/

import { Component, onWillDestroy, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";
import { fetchCcaPartnerSummary } from "@customer_checking_account_pos/js/partner_summary";

/**
 * Financiación de la parte a cuenta corriente: recargo, cuotas, primer vencimiento y
 * frecuencia. Devuelve por getPayload los valores elegidos; cerrar sin confirmar = cancelar.
 */
export class CcaFinancingPopup extends Component {
    static template = "customer_checking_account_pos.CcaFinancingPopup";
    static components = { Dialog };
    static props = {
        order: Object,
        amount: Number,
        maxAmount: Number,
        defaults: Object,
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.pos = usePos();
        const d = this.props.defaults;
        this.state = useState({
            amount: this.props.amount,
            surcharge_percent: d.surcharge_percent,
            installment_count: d.installment_count,
            first_due_date: d.first_due_date,
            frequency: d.frequency,
            summary: null,
            summaryLoaded: false,
        });
        // Sin await: el popup abre al instante con "Consultando cuenta…" y el saldo llega después.
        this.alive = true;
        onWillDestroy(() => (this.alive = false));
        fetchCcaPartnerSummary(this.pos, this.partner).then((summary) => {
            if (this.alive) {
                this.state.summary = summary;
                this.state.summaryLoaded = true;
            }
        });
    }

    get partner() {
        return this.props.order.get_partner();
    }

    get currency() {
        return this.props.order.currency;
    }

    /** Número saneado de un input (vacío o inválido = 0). */
    num(value) {
        const parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    get amount() {
        return roundCurrency(this.num(this.state.amount), this.currency);
    }

    get installments() {
        return Math.max(Math.trunc(this.num(this.state.installment_count)), 1);
    }

    get surcharge() {
        return this.props.order.getCcaSurcharge(this.amount, Math.max(this.num(this.state.surcharge_percent), 0));
    }

    get financed() {
        return roundCurrency(this.amount + this.surcharge, this.currency);
    }

    get installmentValue() {
        return roundCurrency(this.financed / this.installments, this.currency);
    }

    get error() {
        if (this.amount <= 0) {
            return _t("El monto a cuenta corriente debe ser mayor a cero.");
        }
        if (roundCurrency(this.amount - this.props.maxAmount, this.currency) > 0) {
            return _t("El monto a cuenta corriente no puede superar el total del pedido.");
        }
        if (this.num(this.state.surcharge_percent) < 0) {
            return _t("El recargo no puede ser negativo.");
        }
        if (!this.state.first_due_date) {
            return _t("Elegí la fecha del primer vencimiento.");
        }
        return "";
    }

    format(value) {
        return this.env.utils.formatCurrency(value);
    }

    confirm() {
        if (this.error) {
            return;
        }
        this.props.getPayload({
            amount: this.amount,
            surcharge_percent: Math.max(this.num(this.state.surcharge_percent), 0),
            installment_count: this.installments,
            first_due_date: this.state.first_due_date,
            frequency: this.state.frequency,
        });
        this.props.close();
    }

    cancel() {
        this.props.close();
    }
}
