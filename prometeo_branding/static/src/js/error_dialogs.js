/** @odoo-module **/
import { Dialog } from "@web/core/dialog/dialog";
import {
    ClientErrorDialog,
    ErrorDialog,
    NetworkErrorDialog,
    RedirectWarningDialog,
    RPCErrorDialog,
    WarningDialog,
} from "@web/core/errors/error_dialogs";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

const BRAND_NAME = "Prometeo ERP";

/**
 * Cambia la palabra Odoo por la marca en un título ya traducido
 * ("Error de servidor de Odoo" -> "Error de servidor de Prometeo ERP").
 */
function debrand(title) {
    return title ? String(title).replace(/\bOdoo\b/g, BRAND_NAME) : title;
}

Dialog.defaultProps = { ...Dialog.defaultProps, title: BRAND_NAME };

ErrorDialog.title = _t("Error de Prometeo ERP");
ClientErrorDialog.title = _t("Error de cliente de Prometeo ERP");
NetworkErrorDialog.title = _t("Error de red de Prometeo ERP");

patch(RPCErrorDialog.prototype, {
    inferTitle() {
        super.inferTitle();
        this.title = debrand(this.title);
    },
});

patch(WarningDialog.prototype, {
    inferTitle() {
        return debrand(super.inferTitle());
    },
});

patch(RedirectWarningDialog.prototype, {
    setup() {
        super.setup();
        this.title = debrand(this.title);
    },
});
