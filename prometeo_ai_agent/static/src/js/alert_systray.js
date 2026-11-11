/** @odoo-module **/
import { Component, onWillStart, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const REFRESH_MS = 60000;

/**
 * Campana del Agente IA en la barra superior: cantidad de alertas abiertas no vistas.
 * Se refresca cada minuto y al volver a la pestaña; el clic abre la bandeja.
 */
export class AiAlertSystray extends Component {
    static template = "prometeo_ai_agent.AlertSystray";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ count: 0, allowed: false });
        onWillStart(async () => {
            this.state.allowed = await user.hasGroup("prometeo_ai_agent.group_user");
            if (this.state.allowed) {
                await this.refresh();
            }
        });
        onMounted(() => {
            if (!this.state.allowed) {
                return;
            }
            this.interval = setInterval(() => this.refresh(), REFRESH_MS);
            this.onVisibility = () => document.visibilityState === "visible" && this.refresh();
            document.addEventListener("visibilitychange", this.onVisibility);
        });
        onWillUnmount(() => {
            clearInterval(this.interval);
            if (this.onVisibility) {
                document.removeEventListener("visibilitychange", this.onVisibility);
            }
        });
    }

    async refresh() {
        try {
            this.state.count = await this.orm.call("prometeo.ai.alert", "systray_count", []);
        } catch {
            // sin conexión o sin permisos: se deja el último valor
        }
    }

    async onClick() {
        await this.action.doAction("prometeo_ai_agent.action_alert_inbox", { clearBreadcrumbs: true });
        this.refresh();
    }
}

registry.category("systray").add("prometeo_ai_agent.alerts", { Component: AiAlertSystray }, { sequence: 25 });
