/** @odoo-module **/
import { ActionDialog } from "@web/webclient/actions/action_dialog";

// ActionDialog copia Dialog.defaultProps al definirse; según el orden de carga
// se queda con el título "Odoo" aunque Dialog ya esté corregido.
ActionDialog.defaultProps.title = "Prometeo ERP";
