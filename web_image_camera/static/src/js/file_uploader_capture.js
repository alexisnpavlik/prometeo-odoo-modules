/** @odoo-module **/
import { FileUploader } from "@web/views/fields/file_handler";

// Prop nueva: se pasa tal cual al atributo capture del input de archivos
// ("environment" abre la cámara trasera en el teléfono).
FileUploader.props = {
    ...FileUploader.props,
    capture: { type: String, optional: true },
};
