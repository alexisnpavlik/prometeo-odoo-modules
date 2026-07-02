/** @odoo-module **/

import { session } from "@web/session";
import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";

// Initialize Sentry for POS
(async function initSentry() {
    if (!window.Sentry) {
        console.warn("[SENTRY] SDK not found. Sentry will not be initialized.");
        return;
    }

    try {
        const response = await fetch('/prometeo_sentry_monitoring/config');
        const data = await response.json();
        const dsn = data?.dsn;

        if (!dsn) {
            console.warn("[SENTRY] DSN not configured or empty.");
            return;
        }

        window.Sentry.init({
            dsn: dsn,
            sendDefaultPii: true,
            environment: "pos",
            tracesSampleRate: 0,
            beforeSend(event) {
                // Add tags
                event.tags = event.tags || {};
                event.tags.module_source = "point_of_sale";
                event.tags.db_name = session.db || "unknown";
                if (window.sentry_pos_config_id) {
                    event.tags.pos_config_id = window.sentry_pos_config_id;
                }

                // TODO: Patch sobre App.prototype.handleError de Owl (error boundaries)
                // TODO: Buffering offline custom más allá del que ya trae el SDK
                // TODO: Integración con la parte server-side de mega_monitoring (before_send Python, _call_kw patch, Root.dispatch patch)

                return event;
            }
        });
        console.log("[SENTRY] Initialized successfully for POS. Environment: pos, DB:", session.db);
    } catch (error) {
        console.error("[SENTRY] Error initializing Sentry for POS:", error);
    }
})();

// Patch PosStore to capture pos_config_id dynamically
patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        if (this.config && this.config.id) {
            window.sentry_pos_config_id = this.config.id;
            if (window.Sentry && typeof window.Sentry.setTag === "function") {
                window.Sentry.setTag("pos_config_id", this.config.id);
            }
        }
    }
});
