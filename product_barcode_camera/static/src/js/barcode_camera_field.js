/** @odoo-module **/

import { registry } from "@web/core/registry";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class BarcodeCameraField extends CharField {
    static template = "product_barcode_camera.BarcodeCameraField";

    setup() {
        super.setup();
        this.showCamera = isMobileOS() && isBarcodeScannerSupported();
    }

    /**
     * Abre la cámara, lee un código y lo carga en el campo.
     */
    async onCameraClick() {
        let barcode;
        try {
            barcode = await scanBarcode(this.env);
        } catch {
            // El usuario cerró el escáner o denegó la cámara: no es un error.
            return;
        }
        if (barcode) {
            await this.props.record.update({ [this.props.name]: barcode });
        }
    }
}

export const barcodeCameraField = {
    ...charField,
    component: BarcodeCameraField,
};

registry.category("fields").add("barcode_camera", barcodeCameraField);
