/** @odoo-module **/
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { formatCurrency } from "@point_of_sale/app/models/utils/currency";
import { patch } from "@web/core/utils/patch";

// La línea valida la forma de sus datos (en modo debug falla con una clave desconocida).
Orderline.props.line.shape.promotion = { type: Boolean, optional: true };

patch(PosOrderline.prototype, {
    /** Marca como promoción las líneas con una promoción aplicada y tacha el precio de la
     *  lista (el de la sucursal, antes del descuento de la promoción). */
    getDisplayData() {
        const data = super.getDisplayData();
        data.promotion = Boolean(this.promotion_pack_tmpl_id);
        if (data.promotion && this.get_discount()) {
            data.oldUnitPrice = formatCurrency(this.getUnitDisplayPriceBeforeDiscount(), this.currency);
        }
        return data;
    },
});
