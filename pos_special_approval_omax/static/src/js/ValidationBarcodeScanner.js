/** @odoo-module **/

import { BarcodeVideoScanner } from "@web/core/barcode/barcode_video_scanner";

export class ValidationBarcodeScanner extends BarcodeVideoScanner {
    static props = ["onResult"];
    setup() {
        super.setup();
        this.sound = this.env.services["mail.sound_effects"];

        this.props = {
            ...this.props,
            facingMode: "environment",
            onResult: this.props.onResult || ((result) => this.onResult(result)),
            onError: console.error,
            delayBetweenScan: 2000,
        };
    }

    onResult(result) {
        this.env.services["barcode_reader"].scan(result);
        this.sound.play("beep");
    }
}
