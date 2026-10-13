/** @odoo-module **/
import { Component, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { loadJS } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";

// Las fotos del teléfono son grandes: se achican antes de leer el código.
const MAX_SIDE = 1600;

export class BarcodeLookupApp extends Component {
    static template = "stock_barcode_lookup.App";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.photoInput = useRef("photoInput");
        this.state = useState({ code: "", result: null, loading: false });
    }

    /** Video en vivo solo en contexto seguro (HTTPS o localhost); si no, foto. */
    get liveCamera() {
        return window.isSecureContext && isBarcodeScannerSupported();
    }

    async onScan() {
        if (!this.liveCamera) {
            this.photoInput.el.click();
            return;
        }
        let code;
        try {
            code = await scanBarcode(this.env);
        } catch {
            this.notification.add(_t("No se pudo usar la cámara. Probá sacando una foto."), { type: "warning" });
            this.photoInput.el.click();
            return;
        }
        await this.lookup(code);
    }

    async onPhoto(ev) {
        const file = ev.target.files[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        this.state.loading = true;
        try {
            const code = await this.decodeImage(file);
            if (!code) {
                this.notification.add(
                    _t("No se encontró un código en la foto. Acercá la cámara al código, con buena luz."),
                    { type: "warning" }
                );
                return;
            }
            await this.lookup(code);
        } finally {
            this.state.loading = false;
        }
    }

    /** Lee el código de una imagen: BarcodeDetector nativo o, si no hay, ZXing. */
    async decodeImage(file) {
        const canvas = await this.toCanvas(file);
        if ("BarcodeDetector" in window) {
            try {
                const codes = await new window.BarcodeDetector().detect(canvas);
                if (codes.length) {
                    return codes[0].rawValue;
                }
            } catch {
                // Sigue con ZXing.
            }
        }
        await loadJS("/web/static/lib/zxing-library/zxing-library.js");
        // Se lee del canvas: decodeFromImageUrl de ZXing falla incluso con imágenes limpias.
        const ZXing = window.ZXing;
        const reader = new ZXing.MultiFormatReader();
        reader.setHints(new Map([[ZXing.DecodeHintType.TRY_HARDER, true]]));
        for (const Binarizer of [ZXing.HybridBinarizer, ZXing.GlobalHistogramBinarizer]) {
            try {
                const source = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
                return reader.decode(new ZXing.BinaryBitmap(new Binarizer(source))).getText();
            } catch {
                // Prueba con el otro binarizador.
            }
        }
        return null;
    }

    async toCanvas(file) {
        const bitmap = await createImageBitmap(file);
        const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        return canvas;
    }

    async onManualSubmit(ev) {
        ev.preventDefault();
        await this.lookup(this.state.code);
    }

    async lookup(code) {
        code = (code || "").trim();
        if (!code) {
            return;
        }
        this.state.code = code;
        this.state.loading = true;
        try {
            this.state.result = await this.orm.call("product.product", "barcode_lookup", [code]);
        } finally {
            this.state.loading = false;
        }
    }

    openProduct() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.template",
            res_id: this.state.result.template_id,
            views: [[false, "form"]],
        });
    }

    replenish() {
        const { template_id, product_id, code } = this.state.result;
        this.action.doAction("stock.action_product_replenish", {
            additionalContext: { default_product_tmpl_id: template_id, default_product_id: product_id },
            onClose: () => this.lookup(code),
        });
    }

    createProduct() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.template",
            views: [[false, "form"]],
            context: { default_barcode: this.state.result.code },
        });
    }

    reset() {
        this.state.result = null;
        this.state.code = "";
    }
}

registry.category("actions").add("stock_barcode_lookup.app", BarcodeLookupApp);
