/** @odoo-module **/

import { registry } from "@web/core/registry";
import { BarcodeDialog } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { CharField, charField } from "@web/views/fields/char/char_field";
import { useService } from "@web/core/utils/hooks";

// Al reabrir la cámara, algunos Android entregan primero el último frame de la
// sesión anterior: sin este filtro se carga el código del producto previo.
const STALE_FRAME_MS = 1500;
let lastScannedBarcode = null;

export class BarcodeCameraDialog extends BarcodeDialog {
    static template = "product_barcode_camera.BarcodeCameraDialog";

    setup() {
        super.setup();
        this.readyAt = null;
    }

    /**
     * Marca el momento en que la cámara empieza a mostrar imagen.
     */
    onReady() {
        this.readyAt = Date.now();
    }

    /**
     * Descarta el código anterior mientras la cámara arranca; pasado ese
     * margen lo acepta (el usuario puede estar apuntando al mismo código).
     */
    onResult(result) {
        const warmingUp = !this.readyAt || Date.now() - this.readyAt < STALE_FRAME_MS;
        if (warmingUp && result === lastScannedBarcode) {
            return;
        }
        lastScannedBarcode = result;
        super.onResult(result);
    }
}

/**
 * Abre el escáner propio y resuelve con el código leído.
 */
function scanBarcode(dialog) {
    return new Promise((resolve, reject) => {
        dialog.add(BarcodeCameraDialog, {
            facingMode: "environment",
            onResult: resolve,
            onError: reject,
        });
    });
}

export class BarcodeCameraField extends CharField {
    static template = "product_barcode_camera.BarcodeCameraField";

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        // En cualquier dispositivo con cámara accesible (teléfono, tablet o PC con webcam).
        this.showCamera = isBarcodeScannerSupported();
    }

    /**
     * Abre la cámara, lee un código y lo carga en el campo.
     */
    async onCameraClick() {
        let barcode;
        try {
            barcode = await scanBarcode(this.dialog);
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
