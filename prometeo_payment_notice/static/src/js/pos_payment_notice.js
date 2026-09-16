/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Chrome } from "@point_of_sale/app/pos_app";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { esperarBloqueoPago } from "@prometeo_payment_notice/js/payment_notice_lock_dialog";

// La apertura se traba una sola vez por sesión de POS: openOpeningControl
// corre en cada montaje de la pantalla de productos, y sin esta marca el
// cajero se comería la espera cada vez que vuelve del cobro. Guardar el id de
// la sesión en vez de un booleano hace que la marca se limpie sola al abrir la
// caja del día siguiente.
const CLAVE_APERTURA = "prometeo_payment_notice_lock_session";

function aperturaYaBloqueada(sessionId) {
    try {
        return window.localStorage.getItem(CLAVE_APERTURA) === String(sessionId);
    } catch {
        return false;
    }
}

function marcarAperturaBloqueada(sessionId) {
    try {
        window.localStorage.setItem(CLAVE_APERTURA, String(sessionId));
    } catch {
        // Sin localStorage la espera vuelve a salir en cada recarga: molesta
        // más de lo previsto, pero nunca impide operar.
    }
}

export class PosPaymentNoticeBanner extends Component {
    static template = "prometeo_payment_notice.PosBanner";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get visible() {
        const session = this.pos.session || {};
        return session._prometeo_notice_show && session._prometeo_notice_mode === "franja";
    }

    get message() {
        return (this.pos.session || {})._prometeo_notice_message || "";
    }
}

Chrome.components = { ...Chrome.components, PosPaymentNoticeBanner };

patch(PosStore.prototype, {
    /**
     * Muestra el aviso de pago una sola vez al abrir la sesión, cuando el
     * modo configurado es "popup".
     */
    async afterProcessServerData() {
        const result = await super.afterProcessServerData(...arguments);
        const session = this.session || {};
        if (session._prometeo_notice_show && session._prometeo_notice_mode === "popup") {
            try {
                this.dialog.add(AlertDialog, {
                    title: _t("Aviso de pago"),
                    body: session._prometeo_notice_message,
                    confirmLabel: _t("Entendido"),
                });
            } catch (e) {
                console.warn("Aviso de pago: falló al mostrar el popup", e);
            }
        }
        return result;
    },

    /**
     * Traba la apertura de caja antes de dejar ver el control de apertura.
     */
    async openOpeningControl() {
        await this._prometeoBloquearCaja("apertura");
        return super.openOpeningControl(...arguments);
    },

    /**
     * Traba el cierre de caja antes de abrir el popup de cierre.
     */
    async closeSession() {
        await this._prometeoBloquearCaja("cierre");
        return super.closeSession(...arguments);
    },

    /**
     * Espera los segundos que indica el servidor de cobranzas.
     *
     * No mira el modo de aviso del POS: el bloqueo lo decide el servidor y no
     * se apaga desde los Ajustes de esta instalación. Cualquier error se
     * traga: el cobro nunca puede quedar trabado por este módulo.
     */
    async _prometeoBloquearCaja(momento) {
        const session = this.session || {};
        if (!session._prometeo_notice_lock) {
            return;
        }
        if (momento === "apertura") {
            if (aperturaYaBloqueada(session.id)) {
                return;
            }
            marcarAperturaBloqueada(session.id);
        }
        try {
            await esperarBloqueoPago(
                this.dialog,
                session._prometeo_notice_message,
                session._prometeo_notice_lock_seconds
            );
        } catch (e) {
            console.warn("Aviso de pago: falló el bloqueo de caja", e);
        }
    },
});
