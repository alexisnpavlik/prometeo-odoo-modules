/** @odoo-module **/
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

const PROMETEO_URL = "https://prometeo.com.ar/";
const userMenuRegistry = registry.category("user_menuitems");

// Documentación, soporte y cuenta de odoo.com llevan a sitios de Odoo.
for (const key of ["documentation", "support", "odoo_account"]) {
    if (userMenuRegistry.contains(key)) {
        userMenuRegistry.remove(key);
    }
}

/**
 * Acceso a la web de Prometeo en el lugar que ocupaba Documentación.
 */
function prometeoItem() {
    return {
        type: "item",
        id: "prometeo_web",
        description: _t("Soporte Prometeo ERP"),
        href: PROMETEO_URL,
        callback: () => {
            browser.open(PROMETEO_URL, "_blank");
        },
        sequence: 10,
    };
}

userMenuRegistry.add("prometeo_web", prometeoItem);
