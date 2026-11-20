/** @odoo-module **/
// La vista pivote se carga en web.assets_backend_lazy: este patch va en ese bundle.
import { onWillStart } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { PivotRenderer } from "@web/views/pivot/pivot_renderer";
import { isExportRestricted } from "@product_stock_export_restrict/js/export_restrict";

// Pivote: "Descargar xlsx".
patch(PivotRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.exportRestricted = false;
        onWillStart(async () => {
            this.exportRestricted = await isExportRestricted(this.props.model.metaData.resModel);
        });
    },
    onDownloadButtonClicked() {
        if (this.exportRestricted) {
            return;
        }
        return super.onDownloadButtonClicked(...arguments);
    },
});
