/** @odoo-module **/
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
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

    /** Indica si la opción de Ajustes reemplaza el desplegable por la pantalla completa. */
    get simplifyFullscreenApps() {
        return Boolean(session.web_menu_simplify_fullscreen_apps);
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
