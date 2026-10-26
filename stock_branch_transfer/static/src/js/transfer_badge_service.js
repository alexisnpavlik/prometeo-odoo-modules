/** @odoo-module **/
import { registry } from "@web/core/registry";

const REFRESH_MS = 60000;
const BADGE_CLASS = "o_branch_transfer_badge";

// Menú → clave de get_pending_counts
const MENU_COUNTS = {
    "stock_branch_transfer.menu_branch_transfer_root": "total",
    "stock_branch_transfer.menu_branch_transfer_incoming": "incoming",
    "stock_branch_transfer.menu_branch_transfer_sent": "sent",
};

/**
 * Contadores de traslados pendientes en el menú.
 *
 * El total va sobre el ícono de la app (menú de apps); "Por recibir" y
 * "Enviados" llevan el suyo en la barra de la app. En el nombre de la app de
 * la barra superior (o_menu_brand) no se muestra: ahí ya están los submenús.
 * Se busca por data-menu-xmlid para no depender de qué menú de apps está instalado.
 */
export const transferBadgeService = {
    dependencies: ["orm"],
    start(env, { orm }) {
        let counts = {};
        let scheduled = false;

        const paintEl = (el, count) => {
            let badge = el.querySelector(`:scope > .${BADGE_CLASS}`);
            if (!count || el.classList.contains("o_menu_brand")) {
                badge?.remove();
                return;
            }
            if (!badge) {
                badge = document.createElement("span");
                badge.className = `${BADGE_CLASS} badge rounded-pill text-bg-danger`;
                el.appendChild(badge);
            }
            if (badge.textContent !== String(count)) {
                badge.textContent = String(count);
            }
        };

        const paint = () => {
            scheduled = false;
            for (const [xmlid, key] of Object.entries(MENU_COUNTS)) {
                for (const el of document.querySelectorAll(`[data-menu-xmlid="${xmlid}"]`)) {
                    paintEl(el, counts[key]);
                }
            }
        };

        const schedulePaint = () => {
            if (!scheduled) {
                scheduled = true;
                requestAnimationFrame(paint);
            }
        };

        const refresh = async () => {
            try {
                counts = await orm.silent.call("stock.branch.transfer", "get_pending_counts", []);
            } catch {
                counts = {};
            }
            schedulePaint();
        };

        // Los menús se renderizan al abrirlos: se repinta cuando cambia el DOM.
        new MutationObserver(schedulePaint).observe(document.body, { childList: true, subtree: true });
        env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", refresh);
        setInterval(refresh, REFRESH_MS);
        refresh();
    },
};

registry.category("services").add("stock_branch_transfer_badge", transferBadgeService);
