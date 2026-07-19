/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";

export class StockCountScanButton extends Component {
    static template = "stock_count_barcode.ScanButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            cameraSupported: isBarcodeScannerSupported(),
            manual: "",
            busy: false,
        });
    }

    get disabled() {
        return this.state.busy || this.props.record.data.state !== "draft";
    }

    /**
     * Abre la cámara, lee un código y lo procesa.
     */
    async onScanClick() {
        let barcode;
        try {
            barcode = await scanBarcode(this.env);
        } catch {
            // El usuario cerró el escáner o denegó la cámara: no es un error.
            return;
        }
        await this.processBarcode(barcode);
    }

    /**
     * Procesa el código tipeado a mano (PC sin cámara o lector láser USB).
     */
    async onManualSubmit(ev) {
        if (ev.key && ev.key !== "Enter") {
            return;
        }
        const barcode = this.state.manual;
        this.state.manual = "";
        await this.processBarcode(barcode);
    }

    /**
     * Guarda la sesión, manda el código al servidor y abre la carga de cantidad.
     */
    async processBarcode(barcode) {
        if (!barcode || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            // La sesión tiene que estar guardada: el servidor crea la línea.
            await this.props.record.save();
            const result = await this.orm.call(
                "stock.count.session",
                "action_scan_barcode",
                [this.props.record.resId, barcode]
            );
            if (result.error) {
                this.notification.add(result.error, {
                    type: "warning",
                    title: _t("Código no reconocido"),
                });
                return;
            }
            await this.action.doAction(result.action, {
                onClose: () => this.props.record.load(),
            });
        } finally {
            this.state.busy = false;
        }
    }
}

export const stockCountScanButton = {
    component: StockCountScanButton,
};

registry.category("view_widgets").add("stock_count_scan_button", stockCountScanButton);
