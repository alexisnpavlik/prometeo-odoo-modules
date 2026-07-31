/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { formatMonetary } from "@web/views/fields/formatters";
import { _t } from "@web/core/l10n/translation";

/**
 * Barra fija al pie con Guardar y Cancelar, solo en pantalla chica.
 *
 * Imita la barra del punto de venta: dos botones grandes lado a lado, cada uno con una
 * acción arriba y un dato abajo. Odoo ya trae guardar y descartar, pero como dos íconos
 * chicos en el indicador de estado del panel de control (form_status_indicator): una
 * nube y una cruz, arriba de todo. En un celular, cargando una venta en el domicilio,
 * eso no se encuentra.
 */
export class CviMobileSaveBar extends Component {
    static template = "collections_from_vendors_installments.CviMobileSaveBar";
    static props = { ...standardWidgetProps };

    get record() {
        return this.props.record;
    }

    /** Solo aparece si hay algo que guardar: registro nuevo o con cambios. */
    get visible() {
        return this.record.isNew || this.record.dirty;
    }

    /** El total de la venta, como el POS muestra el importe a pagar. */
    get totalLabel() {
        const data = this.record.data;
        if (!data || !data.amount_total) {
            return "";
        }
        return formatMonetary(data.amount_total, { data });
    }

    get discardLabel() {
        return this.record.isNew ? _t("Descartar la venta") : _t("Deshacer cambios");
    }

    async save() {
        await this.record.save();
    }

    async discard() {
        // En un registro nuevo, descartar deja un formulario vacío sin sentido: hay que
        // volver atrás, que es lo que hace el propio form_controller al descartar.
        const wasNew = this.record.isNew;
        await this.record.discard();
        if (wasNew) {
            this.env.config.historyBack?.();
        }
    }
}

registry.category("view_widgets").add("cvi_mobile_save_bar", {
    component: CviMobileSaveBar,
});
