/** @odoo-module **/
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { Orderline } from "@point_of_sale/app/generic_components/orderline/orderline";
import { patch } from "@web/core/utils/patch";

// La línea valida la forma de sus datos (en modo debug falla con una clave desconocida).
Orderline.props.line.shape.promotion = { type: Boolean, optional: true };

patch(PosOrderline.prototype, {
    /** Marca como promoción las líneas de un pack aplicado (el ahorro ya se ve como descuento %). */
    getDisplayData() {
        const data = super.getDisplayData();
        data.promotion = Boolean(this.promotion_pack_tmpl_id);
        return data;
    },
});
