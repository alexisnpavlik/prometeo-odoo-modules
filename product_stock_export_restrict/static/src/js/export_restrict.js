/** @odoo-module **/
import { onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { exportAllItem } from "@web/views/list/export_all/export_all";
import { ListController } from "@web/views/list/list_controller";

export const RESTRICTED_MODELS = [
    "product.template",
    "product.product",
    "stock.quant",
    "stock.move",
    "stock.move.line",
    "product.supplierinfo",
];
const EXPORT_GROUP = "product_stock_export_restrict.group_product_stock_export";

/** True si el modelo está cubierto y el usuario no tiene el grupo de exportación. */
export async function isExportRestricted(resModel) {
    if (!RESTRICTED_MODELS.includes(resModel)) {
        return false;
    }
    return !(await user.hasGroup(EXPORT_GROUP));
}

// Lista: "Exportar" del menú de acciones.
patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        this.exportRestricted = false;
        onWillStart(async () => {
            this.exportRestricted = await isExportRestricted(this.props.resModel);
        });
    },
    getStaticActionMenuItems() {
        const items = super.getStaticActionMenuItems(...arguments);
        const isAvailable = items.export.isAvailable;
        items.export.isAvailable = () => isAvailable() && !this.exportRestricted;
        return items;
    },
    async onDirectExportData() {
        if (this.exportRestricted) {
            return;
        }
        return super.onDirectExportData(...arguments);
    },
});

// Lista: "Exportar todo" del engranaje.
registry.category("cogMenu").add(
    "export-all-menu",
    {
        ...exportAllItem,
        isDisplayed: async (env) =>
            (await exportAllItem.isDisplayed(env)) &&
            !(await isExportRestricted(env.searchModel.resModel)),
    },
    { sequence: 10, force: true }
);
