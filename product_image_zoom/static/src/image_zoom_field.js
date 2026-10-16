/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ImageField, imageField } from "@web/views/fields/image/image_field";
import { FileUploader } from "@web/views/fields/file_handler";
import { Dialog } from "@web/core/dialog/dialog";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

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

    async onUploaded(info) {
        await this.props.onUploaded(info);
        this.props.close();
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
