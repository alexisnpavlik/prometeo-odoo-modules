/** @odoo-module **/
import { Component, useState, onWillStart, onMounted, onWillDestroy } from "@odoo/owl";
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
        this.state = useState({
            matching: [],
            others: [],
            othersCount: 0,
            showOthers: false,
            stale: true,
            lastSyncAt: false,
            loading: true,
            error: false,
            searching: false,
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

        // onWillDestroy y no onWillUnmount: si onWillStart falla, el componente
        // se destruye sin haberse montado nunca y onWillUnmount no corre. El
        // timer y el listener quedarían vivos para siempre, uno por intento de
        // cobro, que es justo la fuga que este registro vino a evitar.
        onWillDestroy(() => {
            this.alive = false;
            clearInterval(this.poller);
            inboxListeners.delete(this.onInboxUpdate);
        });
    }

    /**
     * Relee la bandeja del servidor. Nunca consulta a Mercado Pago.
     *
     * No propaga el error: el POS tiene que poder operar con el servidor caído,
     * y un rechazo suelto acá tumba el onWillStart (y con él la limpieza del
     * poller) o pinta un cartel de error del sistema en cada tick del polling.
     * El diálogo avisa y deja disponible la aprobación manual.
     */
    async refresh() {
        if (!this.alive || this.state.autoImputed) {
            // Con una imputación automática pendiente de confirmar, refrescar la
            // lista debajo del cartel sólo genera parpadeo.
            return;
        }
        let result;
        try {
            result = await this.orm.silent.call(
                "pos.payment.method",
                "get_mp_inbox",
                [[this.props.paymentMethod.id], this.props.amount]
            );
        } catch (error) {
            this._reportError(
                _t("No se pudo leer la bandeja de Mercado Pago. Verificá el pago por otro medio."),
                error
            );
            return;
        }
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
            error: false,
        });
    }

    /**
     * Fuerza una consulta a Mercado Pago y refresca la lista.
     *
     * El cron corre cada minuto (piso de `ir.cron`) y el webhook puede atrasarse
     * o no estar configurado, así que el cajero que sabe que el pago entró
     * necesita una forma de pedirlo sin esperar. El botón se bloquea mientras
     * dura la consulta para que no se dispare una llamada por clic.
     */
    async searchNow() {
        if (!this.alive || this.state.searching) {
            return;
        }
        this.state.searching = true;
        let result;
        try {
            result = await this.orm.silent.call(
                "pos.payment.method",
                "force_mp_sync",
                [[this.props.paymentMethod.id], this.props.amount]
            );
        } catch (error) {
            this._reportError(
                _t("No se pudo consultar a Mercado Pago. Probá de nuevo en unos segundos."),
                error
            );
            if (this.alive) {
                this.state.searching = false;
            }
            return;
        }
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
            error: false,
            searching: false,
        });
    }

    /**
     * Muestra el fallo dentro del diálogo en vez de dejarlo escapar a OWL.
     */
    _reportError(message, error) {
        if (this.alive) {
            this.state.loading = false;
            this.state.error = message;
        }
        console.warn(message, error);
    }

    // Dos filas son indistinguibles si comparten monto y no tienen identificador.
    get isAmbiguous() {
        if (this.state.matching.length < 2) {
            return false;
        }
        const identified = this.state.matching.filter((l) => l.display_payer);
        return identified.length === 0;
    }

    get isSingleMatch() {
        return this.state.matching.length === 1;
    }

    get canConfirmManual() {
        return Boolean(this.state.manualReason.trim());
    }

    /**
     * Imputa la fila elegida. Con `auto` el diálogo queda abierto para deshacer.
     *
     * Atrapa el fallo de transporte por el mismo motivo que `refresh()`: con el
     * servidor caído y una lista vieja en pantalla, el rechazo escaparía al
     * manejador de errores de OWL en vez de avisar dentro del diálogo.
     */
    async pick(line, auto = false) {
        let accepted;
        try {
            accepted = await this.props.onPicked(line, this.isAmbiguous);
        } catch (error) {
            this._reportError(
                _t("No se pudo imputar el pago. Verificá la conexión con el servidor."),
                error
            );
            return;
        }
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
        let undone;
        try {
            undone = await this.props.onUndo();
        } catch (error) {
            this._reportError(
                _t("No se pudo deshacer. Verificá la conexión con el servidor."),
                error
            );
            return;
        }
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
        if (!this.canConfirmManual) {
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
