/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Chrome } from "@point_of_sale/app/pos_app";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { esperarBloqueoPago } from "@prometeo_payment_notice/js/payment_notice_lock_dialog";

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
     *
     * Se apoya en shouldShowOpeningControl, que mira si la sesión sigue en
     * opening_control: así la espera sale cada vez que el cajero intenta
     * abrir la caja —incluso si descarta el control y vuelve a entrar— y no
     * vuelve a salir una vez abierta, aunque openOpeningControl corra de
     * nuevo en cada montaje de la pantalla de productos.
     */
    async openOpeningControl() {
        if (this.shouldShowOpeningControl()) {
            await this._prometeoBloquearCaja();
        }
        return super.openOpeningControl(...arguments);
    },

    /**
     * Traba el cierre de caja antes de abrir el popup de cierre.
     */
    async closeSession() {
        await this._prometeoBloquearCaja();
        return super.closeSession(...arguments);
    },

    /**
     * Espera los segundos que indica el servidor de cobranzas.
     *
     * No mira el modo de aviso del POS: el bloqueo lo decide el servidor y no
     * se apaga desde los Ajustes de esta instalación. Cualquier error se
     * traga: el cobro nunca puede quedar trabado por este módulo.
     */
    async _prometeoBloquearCaja() {
        const session = this.session || {};
        if (!session._prometeo_notice_lock) {
            return;
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
