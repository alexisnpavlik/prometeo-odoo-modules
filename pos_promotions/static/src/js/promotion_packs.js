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

    /** Junta en una línea las del mismo producto y precio que el pack separó (o que quedaron sueltas). */
    _mergePromotionPackLines(lines) {
        const kept = [];
        for (const line of lines) {
            const target = kept.find(
                (other) =>
                    other.product_id.id === line.product_id.id &&
                    other.price_unit === line.price_unit &&
                    other.price_type === line.price_type &&
                    other.getNote() === line.getNote() &&
                    other.get_customer_note() === line.get_customer_note() &&
                    other.is_pos_groupable() &&
                    !other.isLotTracked()
            );
            if (target) {
                target.set_quantity(target.get_quantity() + line.get_quantity());
                if (this.get_selected_orderline() === line) {
                    this.select_orderline(target);
                }
                line.delete();
            } else {
                kept.push(line);
            }
        }
        return kept;
    },

    /** Parte la línea: queda con `qty` unidades y el resto va a una línea nueva sin descuento. */
    _splitPromotionPackLine(line, qty) {
        const rest = line.get_quantity() - qty;
        line.set_quantity(qty);
        this.models["pos.order.line"].create({
            order_id: this,
            product_id: line.product_id,
            qty: rest,
            price_unit: line.price_unit,
            price_type: line.price_type,
            price_extra: line.price_extra,
            full_product_name: line.full_product_name,
            tax_ids: line.tax_ids.map((tax) => ["link", tax]),
            attribute_value_ids: (line.attribute_value_ids || []).map((value) => ["link", value]),
        });
    },

    /**
     * Busca los packs completos en la orden (respetando la cantidad de cada producto del
     * pack) y pone su ahorro como descuento % solo en las unidades que entran en el pack:
     * si sobran, van en otra línea a precio normal. Se recalcula entero en cada cambio.
     */
    applyPromotionPacks() {
        if (this._applyingPromotionPacks || this._promotionPacksPaused || this.finalized) {
            return;
        }
        this._applyingPromotionPacks = true;
        try {
            let lines = this.get_orderlines().filter((line) => this._isPromotionPackCandidate(line));
            for (const line of lines) {
                if (line.promotion_pack_tmpl_id) {
                    line.set_discount(0);
                    line.update({ promotion_pack_tmpl_id: false });
                }
            }
            lines = this._mergePromotionPackLines(lines);

            const available = new Map();
            const unitPrice = new Map();
            for (const line of lines) {
                const id = line.product_id.id;
                available.set(id, (available.get(id) || 0) + line.get_quantity());
                if (!unitPrice.has(id)) {
                    unitPrice.set(id, line.get_unit_price());
                }
            }
            // Por producto: unidades dentro de packs, ahorro y pack. Primero los que más ahorran.
            const packed = new Map();
            const saving = new Map();
            const packByProduct = new Map();
            const packs = this.getPromotionPacks()
                .filter((pack) => pack.components.every((c) => unitPrice.has(c.product.id)))
                .map((pack) => ({
                    ...pack,
                    price: pack.product.lst_price,
                    regular: pack.components.reduce((acc, c) => acc + unitPrice.get(c.product.id) * c.qty, 0),
                }))
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
                    const id = c.product.id;
                    const units = times * c.qty;
                    available.set(id, available.get(id) - units);
                    packed.set(id, (packed.get(id) || 0) + units);
                    saving.set(id, (saving.get(id) || 0) + units * unitPrice.get(id) * ratio);
                    packByProduct.set(id, pack.template);
                }
            }

            for (const [id, units] of packed) {
                // Odoo guarda el descuento con 2 decimales: el total puede diferir del pack en centavos.
                const discount = Math.round((saving.get(id) / (units * unitPrice.get(id))) * 10000) / 100;
                let remaining = units;
                for (const line of lines.filter((l) => l.product_id.id === id)) {
                    if (remaining <= 0) {
                        break;
                    }
                    const take = Math.min(line.get_quantity(), remaining);
                    if (take < line.get_quantity()) {
                        this._splitPromotionPackLine(line, take);
                    }
                    line.set_discount(discount);
                    line.update({ promotion_pack_tmpl_id: packByProduct.get(id) });
                    remaining -= take;
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
        // Pausado mientras Odoo agrega: al sumar a una línea existente, la nueva todavía
        // está en la orden y el recálculo la contaría dos veces.
        order._promotionPacksPaused = true;
        let line;
        try {
            if (product?.is_promotion_pack) {
                const pack = order.getPromotionPacks().find((p) => p.product.id === product.id);
                for (const component of pack?.components || []) {
                    line = await super.addLineToOrder(
                        { product_id: component.product, qty: (vals.qty || 1) * component.qty },
                        order,
                        opts,
                        false
                    );
                }
            } else {
                line = await super.addLineToOrder(...arguments);
            }
        } finally {
            order._promotionPacksPaused = false;
        }
        order.applyPromotionPacks();
        return line;
    },
});
