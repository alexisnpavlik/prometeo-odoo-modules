/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { roundCurrency } from "@point_of_sale/app/models/utils/currency";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

/** Id del producto "Pago Cuenta Corriente" de la caja (record cargado o id crudo). */
export function getCcaPaymentProductId(config) {
    const product = config?.cca_payment_product_id;
    if (product && typeof product === "object") {
        return product.id;
    }
    return product || config?.raw?.cca_payment_product_id || false;
}

/** Neto pagado por id de medio de pago (el vuelto, si está como línea, resta). */
function netByMethod(payments) {
    const totals = {};
    for (const payment of payments) {
        const methodId = payment.payment_method_id?.id;
        totals[methodId] = (totals[methodId] || 0) + payment.get_amount();
    }
    return totals;
}

patch(PosOrder.prototype, {
    /** Líneas de pago con monto hechas con el medio de cuenta corriente. */
    getCcaPaymentLines() {
        return this.payment_ids.filter(
            (p) => p.payment_method_id?.cca_is_checking_account && p.get_amount() !== 0
        );
    },

    /** Monto total pagado con cuenta corriente. */
    getCcaAmount() {
        return roundCurrency(
            this.getCcaPaymentLines().reduce((sum, p) => sum + p.get_amount(), 0),
            this.currency
        );
    },

    /** Líneas del producto de pago de cuenta corriente. */
    getCcaPaymentProductLines() {
        const productId = getCcaPaymentProductId(this.config);
        if (!productId) {
            return [];
        }
        return this.lines.filter((line) => line.product_id?.id === productId);
    },

    /** Indica si el pedido cobra cuotas con el producto de pago. */
    hasCcaPaymentProduct() {
        return this.getCcaPaymentProductLines().length > 0;
    },

    /** Recargo de financiación sobre el monto a cuenta corriente (igual que el servidor). */
    getCcaSurcharge(ccAmount = this.getCcaAmount(), percent = this.cca_surcharge_percent) {
        return roundCurrency((ccAmount * (percent || 0)) / 100, this.currency);
    },

    /** Mismo chequeo que _cca_check_rules del servidor; devuelve el mensaje o null. */
    getCcaValidationError() {
        if (this.lines.some((line) => line.refunded_orderline_id)) {
            return this._getCcaRefundError();
        }
        const ccLines = this.getCcaPaymentLines();
        const productLines = this.getCcaPaymentProductLines();
        if (!ccLines.length && !productLines.length) {
            return null;
        }
        const partner = this.get_partner();
        if (!partner) {
            return _t("Elegí un cliente para operar con cuenta corriente.");
        }
        if (!partner.vat) {
            return _t("Cargá el DNI de %s antes de operar con cuenta corriente.", partner.name);
        }
        if (ccLines.length && productLines.length) {
            return _t("No se puede vender a cuenta corriente y cobrar cuotas en el mismo pedido.");
        }
        const currency = this.currency;
        if (productLines.length) {
            const total = productLines.reduce((sum, line) => sum + line.get_price_with_tax(), 0);
            if (roundCurrency(total, currency) <= 0) {
                return _t("El pago de cuenta corriente debe ser mayor a cero.");
            }
        }
        if (ccLines.length) {
            if (roundCurrency(this.getCcaAmount() - this.get_total_with_tax(), currency) > 0) {
                return _t("El monto a cuenta corriente no puede superar el total del pedido.");
            }
            if (this.lines.some((line) => roundCurrency(line.get_price_with_tax(), currency) < 0)) {
                return _t(
                    "Una venta a cuenta corriente no puede tener líneas negativas: " +
                        "quitá los descuentos en línea o cobrá esa parte con otro medio."
                );
            }
        }
        return null;
    },

    /** Reglas de reembolso del servidor; solo si el pedido original está cargado en el POS. */
    _getCcaRefundError() {
        const originals = [
            ...new Set(
                this.lines
                    .map((line) => line.refunded_orderline_id?.order_id)
                    .filter((order) => order)
            ),
        ];
        if (originals.length > 1) {
            return _t("Un reembolso solo puede devolver productos de un mismo pedido.");
        }
        const original = originals[0];
        if (!original || !original.payment_ids?.length) {
            // Sin el pedido original en memoria, valida el servidor.
            return null;
        }
        const ownCc = this.getCcaPaymentLines();
        const originalCc = original.getCcaPaymentLines();
        const reference = original.pos_reference || original.name;
        if (ownCc.length && !originalCc.length) {
            const names = [...new Set(ownCc.map((p) => p.payment_method_id.name))].join(", ");
            return _t(
                "El pedido %(order)s no se vendió a cuenta corriente: el reembolso no puede usar %(cc)s.",
                { order: reference, cc: names }
            );
        }
        if (!originalCc.length) {
            return null;
        }
        if (this.lines.some((line) => !line.refunded_orderline_id)) {
            return _t(
                "Un reembolso con cuenta corriente no puede incluir productos nuevos: hacé el " +
                    "reembolso y la venta nueva en pedidos separados."
            );
        }
        for (const originalLine of original.lines) {
            if (!originalLine.qty) {
                continue;
            }
            const refunded = -this.lines
                .filter((line) => line.refunded_orderline_id?.id === originalLine.id)
                .reduce((sum, line) => sum + line.get_quantity(), 0);
            if (Math.abs(refunded - originalLine.qty) > 1e-6) {
                return _t("Reembolso parcial de una venta a cuenta corriente: resolvelo desde el backend.");
            }
        }
        const paid = netByMethod(original.payment_ids);
        const refunded = netByMethod(this.payment_ids);
        for (const methodId of new Set([...Object.keys(paid), ...Object.keys(refunded)])) {
            if (roundCurrency((paid[methodId] || 0) + (refunded[methodId] || 0), this.currency)) {
                const names = [...new Set(originalCc.map((p) => p.payment_method_id.name))].join(", ");
                return _t(
                    "El reembolso de una venta a cuenta corriente debe devolverse con los mismos " +
                        "medios y montos del pedido %(order)s: lo financiado con %(cc)s y la entrega " +
                        "con su medio original.",
                    { order: reference, cc: names }
                );
            }
        }
        return null;
    },

    /** Agrega al ticket la línea de cuenta corriente que devuelve el servidor. */
    export_for_printing() {
        const data = super.export_for_printing(...arguments);
        data.cca_receipt_info = this.cca_receipt_info || false;
        return data;
    },
});
