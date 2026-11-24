/** @odoo-module **/
// Sin "Crear" ni "Crear y editar" en los campos de unidad de medida. El bloqueo
// real está en uom.uom.create; esto solo evita ofrecer una opción que va a fallar.
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

if (session.web_menu_simplify_block_uom_create) {
    patch(Many2OneField.prototype, {
        setup() {
            super.setup(...arguments);
            if (this.relation === "uom.uom") {
                this.quickCreate = null;
            }
        },
        computeActiveActions(props) {
            super.computeActiveActions(...arguments);
            if (this.relation === "uom.uom") {
                this.state.activeActions.create = false;
                this.state.activeActions.createEdit = false;
            }
        },
    });
}
