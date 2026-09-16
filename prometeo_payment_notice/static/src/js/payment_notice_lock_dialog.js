/** @odoo-module **/

import { Component, onWillDestroy, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

/**
 * Diálogo sin salida: sin Escape y sin la X del encabezado.
 *
 * Es el mismo truco que usa el core en OpeningControlPopup: Dialog engancha
 * la tecla con useHotkey y llama a onEscape(), así que pisarlo vacío alcanza.
 * La X vive en el slot del header, que se saca con header="false".
 */
class DialogSinSalida extends Dialog {
    onEscape() {}
}

export class PaymentNoticeLockDialog extends Component {
    static template = "prometeo_payment_notice.LockDialog";
    static components = { Dialog: DialogSinSalida };
    static props = {
        message: { type: String, optional: true },
        seconds: { type: Number },
        close: { type: Function },
    };

    setup() {
        this.state = useState({ restante: Math.max(this.props.seconds, 0) });
        this.tick = setInterval(() => {
            this.state.restante -= 1;
            if (this.state.restante <= 0) {
                clearInterval(this.tick);
            }
        }, 1000);
        onWillDestroy(() => clearInterval(this.tick));
    }

    get listo() {
        return this.state.restante <= 0;
    }

    get reloj() {
        const total = Math.max(this.state.restante, 0);
        const minutos = String(Math.floor(total / 60)).padStart(2, "0");
        const segundos = String(total % 60).padStart(2, "0");
        return `${minutos}:${segundos}`;
    }
}

/**
 * Muestra el bloqueo y resuelve recién cuando el cajero lo cierra.
 *
 * Con seconds en 0 no bloquea nada: resuelve al toque, así un mal dato del
 * servidor no deja un cartel sin botón en pantalla.
 */
export function esperarBloqueoPago(dialogService, message, seconds) {
    if (!seconds || seconds <= 0) {
        return Promise.resolve();
    }
    return new Promise((resolve) => {
        dialogService.add(
            PaymentNoticeLockDialog,
            { message, seconds },
            { onClose: resolve }
        );
    });
}
