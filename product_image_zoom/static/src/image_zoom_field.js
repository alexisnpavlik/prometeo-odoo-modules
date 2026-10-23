/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ImageField, imageField } from "@web/views/fields/image/image_field";
import { FileUploader } from "@web/views/fields/file_handler";
import { Dialog } from "@web/core/dialog/dialog";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

// Odoo guarda image_1920 a 1920 px como máximo: achicar antes de subir no pierde calidad.
const MAX_SIDE = 1920;
const JPEG_QUALITY = 0.85;

/**
 * Achica una imagen base64 a MAX_SIDE px y la recodifica en JPEG.
 * Si falla o el resultado no es más chico, devuelve la original.
 */
async function compressImage(base64, type) {
    if (!type.startsWith("image/") || type === "image/svg+xml" || type === "image/gif") {
        return base64;
    }
    try {
        const img = new Image();
        img.src = `data:${type};base64,${base64}`;
        await img.decode();
        const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.naturalWidth * scale);
        canvas.height = Math.round(img.naturalHeight * scale);
        const ctx = canvas.getContext("2d");
        // Fondo blanco: JPEG no tiene transparencia (PNG con fondo transparente)
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        const compressed = canvas.toDataURL("image/jpeg", JPEG_QUALITY).split(",")[1];
        return compressed.length < base64.length ? compressed : base64;
    } catch {
        return base64;
    }
}

/**
 * Popup con la imagen en grande y botones grandes para cambiarla o quitarla.
 * El dialog service inyecta automáticamente la prop `close`.
 */
class ImageZoomDialog extends Component {
    static template = "product_image_zoom.ImageZoomDialog";
    static components = { Dialog, FileUploader };
    static props = {
        src: { type: String, optional: true },
        readonly: Boolean,
        isMobile: Boolean,
        acceptedFileExtensions: String,
        onUploaded: Function,
        onRemove: Function,
        close: Function,
    };

    get cameraSupported() {
        // La prop `capture` solo existe si está instalado web_image_camera
        return this.props.isMobile && "capture" in FileUploader.props;
    }

    /**
     * Cierra el popup enseguida para seguir cargando el producto;
     * la compresión termina en segundo plano y recién ahí se carga la imagen.
     */
    async onUploaded(info) {
        this.props.close();
        const data = await compressImage(info.data, info.type);
        await this.props.onUploaded({ ...info, data });
    }

    onRemove() {
        this.props.onRemove();
        this.props.close();
    }
}

/**
 * ImageField sin los botones chicos superpuestos: tocar la imagen abre
 * ImageZoomDialog, que concentra ver, cambiar y quitar.
 */
class ImageZoomField extends ImageField {
    static template = "product_image_zoom.ImageZoomField";

    setup() {
        super.setup();
        this.dialogService = useService("dialog");
    }

    get hasImage() {
        return Boolean(this.props.record.data[this.props.name]) && this.state.isValid;
    }

    openZoom() {
        if (!this.hasImage && this.props.readonly) {
            return;
        }
        this.dialogService.add(ImageZoomDialog, {
            src: this.hasImage ? this.getUrl(this.props.name) : undefined,
            readonly: Boolean(this.props.readonly),
            isMobile: this.isMobile,
            acceptedFileExtensions: this.props.acceptedFileExtensions,
            onUploaded: (info) => this.onFileUploaded(info),
            onRemove: () => this.onFileRemove(),
        });
    }
}

// Registrar como "image_zoom" heredando metadata de imageField (supportedTypes, options, etc.)
registry.category("fields").add("image_zoom", {
    ...imageField,
    component: ImageZoomField,
    displayName: "Image Zoom",
});
