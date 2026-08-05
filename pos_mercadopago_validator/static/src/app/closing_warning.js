/** @odoo-module **/
import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { Dialog } from "@web/core/dialog/dialog";
import { ClosePosPopup } from "@point_of_sale/app/navbar/closing_popup/closing_popup";
import { ask } from "@point_of_sale/app/store/make_awaitable_dialog";

/**
 * Aviso informativo de pagos de Mercado Pago sin imputar al cerrar la caja.
 *
 * Un pago acreditado sin venta asociada es dinero real fuera de la caja: el
 * único objetivo de este diálogo es que el cajero lo note ahora, no una
 * semana después reconciliando la cuenta. Por eso tiene un solo botón que
 * siempre deja seguir con el cierre.
 */
export class MercadoPagoClosingWarningDialog extends Component {
    static template = "pos_mercadopago_validator.ClosingWarningDialog";
    static components = { Dialog };
    static props = {
        payments: Array,
        confirm: Function,
        cancel: Function,
        close: Function,
    };

    /**
     * Formatea un monto con la moneda de la caja.
     */
    formatAmount(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    /**
     * Muestra la hora local del pago a partir del ISO que manda el servidor.
     */
    formatTime(iso) {
        if (!iso) {
            return "";
        }
        // El servidor serializa datetimes ingenuos en UTC. Sin la Z el
        // navegador los leería como hora local y mostraría una hora que
        // no ocurrió (mismo ajuste que inbox_dialog.js).
        const utc = /(Z|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`;
        // h23: 24 horas con medianoche en 00, no en 24 como devuelve hour12:false
        // en algunos navegadores.
        return new Date(utc).toLocaleTimeString("es-AR", { hourCycle: "h23" });
    }
}

patch(ClosePosPopup.prototype, {
    /**
     * Antes de confirmar el cierre, avisa si quedaron pagos de Mercado Pago
     * sin imputar durante la sesión.
     *
     * El aviso nunca bloquea el cierre: es sólo informativo. `super.confirm()`
     * tiene que correr pase lo que pase, así que TODO lo que puede fallar
     * -la consulta, la forma de lo que devuelve, y el diálogo mismo, que
     * puede lanzar al construirse o al renderizar- va dentro de un único
     * `try/catch` que nunca hace `return` adentro: si algo revienta acá, se
     * loguea y se cae igual al `super.confirm()` de abajo, fuera del bloque.
     */
    async confirm() {
        try {
            const unmatched = await this.pos.data.call(
                "pos.session",
                "get_mercadopago_unmatched",
                [this.pos.session.id]
            );
            // Un resultado que no es array (null, undefined, un objeto de
            // error mal formado) se trata como "no hay huérfanos", nunca
            // como un motivo para bloquear el cierre.
            if (Array.isArray(unmatched) && unmatched.length) {
                // Diálogo puramente informativo: se espera a que el cajero lo
                // cierre (con el único botón, o con Escape/la X) y se
                // continúa igual, sea cual sea el resultado de la promesa.
                await ask(
                    this.dialog,
                    { payments: unmatched },
                    {},
                    MercadoPagoClosingWarningDialog
                );
            }
        } catch (error) {
            console.warn(
                _t("No se pudo consultar los pagos de Mercado Pago sin imputar"),
                error
            );
        }
        return super.confirm(...arguments);
    },
});
