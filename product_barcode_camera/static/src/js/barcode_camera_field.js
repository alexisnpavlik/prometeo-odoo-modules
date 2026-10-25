/** @odoo-module **/

import { registry } from "@web/core/registry";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class BarcodeCameraField extends CharField {
    static template = "product_barcode_camera.BarcodeCameraField";

    setup() {
        super.setup();
        // En cualquier dispositivo con cámara accesible (teléfono, tablet o PC con webcam).
        this.showCamera = isBarcodeScannerSupported();
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
