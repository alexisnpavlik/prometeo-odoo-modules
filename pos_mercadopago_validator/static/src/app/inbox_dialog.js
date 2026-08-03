/** @odoo-module **/
import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

/**
 * Suscriptores vivos al evento de bus de la bandeja.
 *
 * `connectWebSocket` no tiene contraparte para desuscribirse: si cada diálogo
 * abriera su propio canal, cada cobro dejaría un handler más apuntando a un
 * componente ya destruido. El canal se abre una sola vez en pos_store.js y los
 * diálogos entran y salen de este registro.
 */
export const inboxListeners = new Set();

export class MercadoPagoInboxDialog extends Component {
    static template = "pos_mercadopago_validator.InboxDialog";
    static components = { Dialog };
    static props = {
        paymentMethod: Object,
        amount: Number,
        onPicked: Function,
        onUndo: Function,
        onDone: Function,
        onManualApproval: Function,
        onCancel: Function,
        close: Function,
    };

    setup() {
        this.orm = useService("orm");
        this.pos = useService("pos");
        this.state = useState({
            matching: [],
            others: [],
            othersCount: 0,
            showOthers: false,
            stale: true,
            lastSyncAt: false,
            loading: true,
            autoImputed: false,
            manualStep: 0,
            manualReason: "",
        });

        // El refresco es asincrónico: sin esta bandera, una respuesta que llega
        // después de cerrar el diálogo escribiría sobre un componente destruido.
        this.alive = true;

        onWillStart(async () => {
            await this.refresh();
        });

        onMounted(async () => {
            // La imputación automática se hace ya montado: cerrar o mutar el
            // diálogo durante onWillStart deja el overlay a medio construir.
            if (
                this.state.matching.length === 1 &&
                this.props.paymentMethod.auto_impute_single_match
            ) {
                await this.pick(this.state.matching[0], true);
            }
        });

        this.poller = setInterval(
            () => this.refresh(),
            (this.props.paymentMethod.poll_interval_seconds || 10) * 1000
        );

        this.onInboxUpdate = () => this.refresh();
        inboxListeners.add(this.onInboxUpdate);

        onWillUnmount(() => {
            this.alive = false;
            clearInterval(this.poller);
            inboxListeners.delete(this.onInboxUpdate);
        });
    }

    /**
     * Relee la bandeja del servidor. Nunca consulta a Mercado Pago.
     */
    async refresh() {
        if (!this.alive || this.state.autoImputed) {
            // Con una imputación automática pendiente de confirmar, refrescar la
            // lista debajo del cartel sólo genera parpadeo.
            return;
        }
        const result = await this.orm.silent.call(
            "pos.payment.method",
            "get_mp_inbox",
            [[this.props.paymentMethod.id], this.props.amount]
        );
        if (!this.alive) {
            return;
        }
        Object.assign(this.state, {
            matching: result.matching,
            others: result.others,
            othersCount: result.others_count,
            stale: result.stale,
            lastSyncAt: result.last_sync_at,
            loading: false,
        });
    }

    // Dos filas son indistinguibles si comparten monto y no tienen identificador.
    get isAmbiguous() {
        if (this.state.matching.length < 2) {
            return false;
        }
        const identified = this.state.matching.filter((l) => l.display_payer);
        return identified.length === 0;
    }

    /**
     * Imputa la fila elegida. Con `auto` el diálogo queda abierto para deshacer.
     */
    async pick(line, auto = false) {
        const accepted = await this.props.onPicked(line, this.isAmbiguous);
        if (!accepted) {
            await this.refresh();
            return;
        }
        if (auto) {
            this.state.autoImputed = line;
            return;
        }
        this.props.onDone();
        this.props.close();
    }

    /**
     * Confirma la imputación automática y cierra el diálogo.
     */
    acceptAuto() {
        this.props.onDone();
        this.props.close();
    }

    /**
     * Deshace la imputación automática y devuelve el cajero a la lista.
     */
    async undoAuto() {
        const undone = await this.props.onUndo();
        if (undone) {
            this.state.autoImputed = false;
            await this.refresh();
        }
    }

    /**
     * Muestra la hora local del pago a partir del ISO que manda el servidor.
     */
    formatTime(iso) {
        if (!iso) {
            return "";
        }
        // El servidor serializa datetimes ingenuos en UTC. Sin la Z el navegador
        // los leería como hora local y mostraría una hora que no ocurrió.
        const utc = /(Z|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`;
        return new Date(utc).toLocaleTimeString("es-AR");
    }

    /**
     * Formatea un monto con la moneda de la caja.
     */
    formatAmount(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    /**
     * Abre el primer paso de la aprobación manual.
     */
    startManual() {
        this.state.manualStep = 1;
    }

    /**
     * Avanza la doble confirmación y registra la aprobación en el segundo paso.
     */
    async confirmManual() {
        if (!this.state.manualReason.trim()) {
            return;
        }
        if (this.state.manualStep === 1) {
            this.state.manualStep = 2;
            return;
        }
        await this.props.onManualApproval(this.state.manualReason);
        this.props.close();
    }

    /**
     * Cancela el cobro: la línea vuelve a quedar pendiente.
     */
    cancel() {
        this.props.onCancel();
        this.props.close();
    }

    get staleLabel() {
        if (!this.state.lastSyncAt) {
            return _t("La bandeja nunca se sincronizó con Mercado Pago.");
        }
        return _t(
            "Datos desactualizados. Última sincronización: %s",
            this.formatTime(this.state.lastSyncAt)
        );
    }
}
