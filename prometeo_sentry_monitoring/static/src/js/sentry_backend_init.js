/** @odoo-module **/

import { session } from "@web/session";

// Initialize Sentry for backend web assets
(async function initSentry() {
    // Guard against initializing in POS context if they are loaded together
    if (window.location.pathname.includes('/pos/')) {
        return;
    }

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
            environment: "backend",
            tracesSampleRate: 0,
            beforeSend(event) {
                // Add tags
                event.tags = event.tags || {};
                event.tags.module_source = "backend";
                event.tags.db_name = session.db || "unknown";

                // TODO: Patch sobre App.prototype.handleError de Owl (error boundaries)
                // TODO: Buffering offline custom más allá del que ya trae el SDK
                // TODO: Integración con la parte server-side de mega_monitoring (before_send Python, _call_kw patch, Root.dispatch patch)

                return event;
            }
        });
        console.log("[SENTRY] Initialized successfully for Backend. Environment: backend, DB:", session.db);
    } catch (error) {
        console.error("[SENTRY] Error initializing Sentry for Backend:", error);
    }
})();
