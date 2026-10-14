/** @odoo-module **/
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { useExternalListener, useState } from "@odoo/owl";

patch(NavBar.prototype, {
    setup() {
        super.setup();
        this.simplifyHome = useState({ open: false });
        useExternalListener(window, "keydown", (ev) => {
            if (ev.key === "Escape" && this.simplifyHome.open) {
                this.simplifyHome.open = false;
            }
        });
    },

    /** Siempre activo: para volver al desplegable se desinstala el módulo. */
    get simplifyFullscreenApps() {
        return true;
    },

    toggleSimplifyHome() {
        this.simplifyHome.open = !this.simplifyHome.open;
    },

    /** Cierra la pantalla de apps y abre la elegida. */
    onSimplifyHomeSelect(app) {
        this.simplifyHome.open = false;
        this.onNavBarDropdownItemSelection(app);
    },
});
