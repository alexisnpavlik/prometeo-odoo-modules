/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { isDisplayStandalone } from "@web/core/browser/feature_detection";

export class PwaInstallBanner extends Component {
    static template = "web_pwa_install_banner.PwaInstallBanner";
    static props = {};

    setup() {
        // El servicio es reactive: sin useState el banner no se re-renderiza al descartar
        this.pwa = useState(useService("pwa"));
        this.ui = useService("ui");
    }

    get isVisible() {
        return (
            this.ui.isSmall &&
            !isDisplayStandalone() &&
            this.pwa.isAvailable &&
            this.pwa.canPromptToInstall
        );
    }

    onInstall() {
        this.pwa.show();
    }

    onDismiss() {
        this.pwa.decline();
    }
}

registry.category("main_components").add("web_pwa_install_banner", {
    Component: PwaInstallBanner,
});
