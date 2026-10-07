/** @odoo-module **/
// Los imports garantizan que los ítems ya estén registrados antes de quitarlos.
import "@mail/core/public_web/messaging_menu";
import "@mail/core/web/activity_menu";
import "@mail/discuss/call/common/call_menu";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

if (session.web_menu_simplify_hide_systray) {
    const systray = registry.category("systray");
    for (const key of ["mail.messaging_menu", "mail.activity_menu", "discuss.CallMenu"]) {
        if (systray.contains(key)) {
            systray.remove(key);
        }
    }
    // Las ventanas de chat se registran al iniciar su servicio: se ocultan por CSS.
    document.documentElement.classList.add("o_web_menu_simplify_hide_chat");
}
