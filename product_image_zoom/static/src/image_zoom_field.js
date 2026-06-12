/** @odoo-module **/

import { registry } from "@web/core/registry";
import { ImageField, imageField } from "@web/views/fields/image/image_field";
import { Dialog } from "@web/core/dialog/dialog";
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * Modal que muestra la imagen en alta resolución.
 * El dialog service inyecta automáticamente la prop `close`.
 */
class ImageZoomDialog extends Component {
    static template = "product_image_zoom.ImageZoomDialog";
    static components = { Dialog };
    static props = { src: String, close: Function };
}

/**
 * Widget que envuelve ImageField y agrega el botón lupa overlay.
 * Al hacer clic en la lupa llama al dialog service para abrir ImageZoomDialog.
 * El clic en la imagen original (upload/edición) no se ve afectado.
 */
class ImageZoomField extends Component {
    static template = "product_image_zoom.ImageZoomField";
    static components = { ImageField };
    static props = ["*"]; // acepta y reenvía todos los props de ImageField

    setup() {
        this.dialogService = useService("dialog");
    }

    openZoom(ev) {
        const { record, name } = this.props;
        // No abrir si no hay imagen o el record aún no fue guardado
        if (!record.resId || !record.data[name]) {
            return;
        }
        const src = `/web/image/${record.resModel}/${record.resId}/${name}`;
        this.dialogService.add(ImageZoomDialog, { src });
    }
}

// Registrar como "image_zoom" heredando metadata de imageField (supportedTypes, etc.)
registry.category("fields").add("image_zoom", {
    ...imageField,
    component: ImageZoomField,
    displayName: "Image Zoom",
});
