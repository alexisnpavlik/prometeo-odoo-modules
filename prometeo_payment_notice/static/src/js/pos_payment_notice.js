/** @odoo-module **/

import { Component } from "@odoo/owl";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { Chrome } from "@point_of_sale/app/pos_app";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";

export class PosPaymentNoticeBanner extends Component {
    static template = "prometeo_payment_notice.PosBanner";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get visible() {
        const session = this.pos.session || {};
        return session.prometeo_notice_show && session.prometeo_notice_mode === "franja";
    }

    get message() {
        return (this.pos.session || {}).prometeo_notice_message || "";
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
        if (session.prometeo_notice_show && session.prometeo_notice_mode === "popup") {
            try {
                this.dialog.add(AlertDialog, {
                    title: _t("Aviso de pago"),
                    body: session.prometeo_notice_message,
                    confirmLabel: _t("Entendido"),
                });
            } catch (e) {
                console.warn("Aviso de pago: falló al mostrar el popup", e);
            }
        }
        return result;
    },
});
