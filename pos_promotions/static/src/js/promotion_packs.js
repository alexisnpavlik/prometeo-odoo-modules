/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";

const recordId = (value) => (value && typeof value === "object" ? value.id : value);

patch(PosOrder.prototype, {
    /** Packs activos cargados en el POS: {template, price, components: [{product, qty}]}. */
    getPromotionPacks() {
        const packs = new Map();
        for (const line of this.models["pos.promotion.pack.line"].getAll()) {
            const tmplId = recordId(line.pack_tmpl_id);
            if (!packs.has(tmplId)) {
                const packProduct = this.models["product.product"].find(
                    (product) => recordId(product.product_tmpl_id) === tmplId
                );
                if (!packProduct) {
                    continue;
                }
                packs.set(tmplId, { template: packProduct.product_tmpl_id, product: packProduct, components: [] });
            }
            if (line.product_id) {
                packs.get(tmplId).components.push({ product: line.product_id, qty: line.quantity });
            }
        }
        return [...packs.values()].filter((pack) => pack.components.length);
    },

    /** Líneas que puede tocar un pack: ventas a precio de lista sin descuento del cajero. */
    _isPromotionPackCandidate(line) {
        return (
            line.get_quantity() > 0 &&
            line.price_type !== "manual" &&
            !line.refunded_orderline_id &&
            !line.combo_parent_id &&
            !line.combo_line_ids?.length &&
            (!line.get_discount() || line.promotion_pack_tmpl_id)
        );
    },

    /**
     * Busca los packs completos en la orden y reparte su ahorro como descuento % en las
     * líneas de sus productos. Se recalcula entero en cada cambio de la orden.
     */
    applyPromotionPacks() {
        if (this._applyingPromotionPacks || this.finalized) {
            return;
        }
        this._applyingPromotionPacks = true;
        try {
            const lines = this.get_orderlines().filter((line) => this._isPromotionPackCandidate(line));
            const available = new Map();
            for (const line of lines) {
                const id = line.product_id.id;
                available.set(id, (available.get(id) || 0) + line.get_quantity());
            }
            // Ahorro y pack por producto. Primero los packs que más ahorran.
            const saving = new Map();
            const packByProduct = new Map();
            const packs = this.getPromotionPacks()
                .map((pack) => {
                    const regular = pack.components.reduce(
                        (acc, c) => acc + (lines.find((l) => l.product_id.id === c.product.id)?.get_unit_price() ?? c.product.lst_price) * c.qty,
                        0
                    );
                    return { ...pack, regular, price: pack.product.lst_price };
                })
                .filter((pack) => pack.regular > pack.price)
                .sort((a, b) => b.regular - b.price - (a.regular - a.price));
            for (const pack of packs) {
                const times = Math.min(
                    ...pack.components.map((c) => Math.floor((available.get(c.product.id) || 0) / c.qty))
                );
                if (!(times > 0)) {
                    continue;
                }
                const ratio = 1 - pack.price / pack.regular;
                for (const c of pack.components) {
                    const unit = lines.find((l) => l.product_id.id === c.product.id).get_unit_price();
                    available.set(c.product.id, available.get(c.product.id) - times * c.qty);
                    saving.set(c.product.id, (saving.get(c.product.id) || 0) + times * c.qty * unit * ratio);
                    packByProduct.set(c.product.id, pack.template);
                }
            }
            for (const line of lines) {
                const id = line.product_id.id;
                const productLines = lines.filter((l) => l.product_id.id === id);
                const productTotal = productLines.reduce((acc, l) => acc + l.get_unit_price() * l.get_quantity(), 0);
                const lineTotal = line.get_unit_price() * line.get_quantity();
                const lineSaving = productTotal ? ((saving.get(id) || 0) * lineTotal) / productTotal : 0;
                // Odoo guarda el descuento con 2 decimales: el total puede diferir del pack en centavos.
                const discount = lineTotal ? Math.round((lineSaving / lineTotal) * 10000) / 100 : 0;
                const pack = discount > 0 ? packByProduct.get(id) : false;
                if (Math.abs(line.get_discount() - discount) > 1e-6) {
                    line.set_discount(discount);
                }
                if (recordId(line.promotion_pack_tmpl_id) !== recordId(pack)) {
                    line.update({ promotion_pack_tmpl_id: pack || false });
                }
            }
        } finally {
            this._applyingPromotionPacks = false;
        }
    },

    removeOrderline(line) {
        const res = super.removeOrderline(...arguments);
        this.applyPromotionPacks();
        return res;
    },

    set_pricelist(pricelist) {
        const res = super.set_pricelist(...arguments);
        this.applyPromotionPacks();
        return res;
    },
});

patch(PosOrderline.prototype, {
    set_quantity(quantity, keep_price) {
        const res = super.set_quantity(...arguments);
        this.order_id?.applyPromotionPacks();
        return res;
    },
});

patch(PosStore.prototype, {
    /** Tocar o escanear un pack agrega sus productos; el pack se aplica solo al estar completos. */
    async addLineToOrder(vals, order, opts = {}, configure = true) {
        const product = typeof vals.product_id === "number"
            ? this.data.models["product.product"].get(vals.product_id)
            : vals.product_id;
        if (product?.is_promotion_pack) {
            const pack = order.getPromotionPacks().find((p) => p.product.id === product.id);
            let last;
            for (const component of pack?.components || []) {
                last = await super.addLineToOrder(
                    { product_id: component.product, qty: (vals.qty || 1) * component.qty },
                    order,
                    opts,
                    false
                );
            }
            order.applyPromotionPacks();
            return last;
        }
        const line = await super.addLineToOrder(...arguments);
        order.applyPromotionPacks();
        return line;
    },
});
