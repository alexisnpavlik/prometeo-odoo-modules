/** @odoo-module **/
import { registry } from "@web/core/registry";

const MENU_XMLID = "stock_branch_transfer.menu_branch_transfer_root";
const REFRESH_MS = 60000;
const BADGE_CLASS = "o_branch_transfer_badge";

/**
 * Contador de traslados pendientes sobre el ícono de la app "Traslados".
 *
 * En vez de parchear un template concreto, busca cualquier elemento con
 * data-menu-xmlid del menú raíz: así funciona igual en el dropdown de apps
 * nativo, el sidebar móvil y web_fullscreen_apps_menu.
 */
export const transferBadgeService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        let count = 0;

        const paint = () => {
            const selector = `[data-menu-xmlid="${MENU_XMLID}"]`;
            for (const el of document.querySelectorAll(selector)) {
                let badge = el.querySelector(`:scope > .${BADGE_CLASS}`);
                if (!count) {
                    badge?.remove();
                    continue;
                }
                if (!badge) {
                    badge = document.createElement("span");
                    badge.className = `${BADGE_CLASS} badge rounded-pill text-bg-danger`;
                    el.appendChild(badge);
                }
                if (badge.textContent !== String(count)) {
                    badge.textContent = String(count);
                }
            }
        };

        const refresh = async () => {
            try {
                count = await orm.silent.call("stock.branch.transfer", "get_pending_count", []);
            } catch {
                count = 0;
            }
            paint();
        };

        // El menú de apps se renderiza al abrirlo: se repinta cuando cambia el DOM.
        new MutationObserver(paint).observe(document.body, { childList: true, subtree: true });
        env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", refresh);
        setInterval(refresh, REFRESH_MS);
        refresh();
    },
};

registry.category("services").add("stock_branch_transfer_badge", transferBadgeService);
