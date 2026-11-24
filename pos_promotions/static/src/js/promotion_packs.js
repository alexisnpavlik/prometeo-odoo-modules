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
        // Producto de cada pack, indexado una vez: buscarlo por pack recorría todo el catálogo.
        const packProducts = new Map();
        for (const product of this.models["product.product"].filter((p) => p.is_promotion_pack)) {
            packProducts.set(recordId(product.product_tmpl_id), product);
        }
        for (const line of this.models["pos.promotion.pack.line"].getAll()) {
            const tmplId = recordId(line.pack_tmpl_id);
            if (!packs.has(tmplId)) {
                const packProduct = packProducts.get(tmplId);
                if (!packProduct) {
                    continue;
                }
                packs.set(tmplId, {
                    template: packProduct.product_tmpl_id,
                    product: packProduct,
                    data: line.promotion_data_json || {},
                    components: [],
                });
            }
            if (line.product_id) {
                packs.get(tmplId).components.push({ product: line.product_id, qty: line.quantity });
            }
        }
        return [...packs.values()].filter((pack) => pack.components.length);
    },

    /** Fecha local de la caja como "AAAA-MM-DD", comparable con las fechas de validez. */
    _getPromotionToday() {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    },

    /** Precio de la promoción: % sobre el precio de la lista de la orden, o precio fijo. */
    _getPromotionPackPrice(pack, regular) {
        if (pack.data.mode === "percent") {
            return regular * (1 - (pack.data.percent || 0) / 100);
        }
        return pack.product.lst_price;
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
                    // Un combo más caro que los sueltos sube el precio: vuelve al de la lista.
                    const listPrice = line.product_id.get_price(
                        this.pricelist_id, line.get_quantity(), line.price_extra || 0
                    );
                    if (Number.isFinite(listPrice)) {
                        line.set_unit_price(listPrice);
                    }
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
            // Por producto: unidades dentro de packs, ahorro (negativo si es recargo) y pack. Primero los que más ahorran.
            const packed = new Map();
            const saving = new Map();
            const packByProduct = new Map();
            // El precio normal es el de la lista de la orden (precio de la sucursal); la
            // promoción descuenta sobre él sin tocarla.
            const packs = this._getActivePromotionPacks()
                .filter((pack) => pack.components.every((c) => unitPrice.has(c.product.id)))
                .map((pack) => {
                    const regular = pack.components.reduce(
                        (acc, c) => acc + unitPrice.get(c.product.id) * c.qty,
                        0
                    );
                    return { ...pack, regular, price: this._getPromotionPackPrice(pack, regular) };
                })
                // Un combo puede costar más que los sueltos: también se aplica (sube el precio).
                .filter((pack) => pack.price > 0 && pack.regular > 0 && pack.regular !== pack.price)
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
                // Un producto a $0 en la lista no lleva parte del descuento ni del recargo
                // (sin esto, 0 / 0 da NaN y Odoo rompe al recibir el precio).
                const base = units * unitPrice.get(id);
                const share = base ? saving.get(id) / base : 0;
                const discount = Math.round(share * 10000) / 100;
                let remaining = units;
                for (const line of lines.filter((l) => l.product_id.id === id)) {
                    if (remaining <= 0) {
                        break;
                    }
                    const take = Math.min(line.get_quantity(), remaining);
                    if (take < line.get_quantity()) {
                        this._splitPromotionPackLine(line, take);
                    }
                    if (discount >= 0) {
                        line.set_discount(discount);
                    } else {
                        // Recargo: Odoo no acepta descuentos negativos, se sube el precio unitario.
                        line.set_unit_price(unitPrice.get(id) * (1 - share));
                    }
                    line.update({ promotion_pack_tmpl_id: packByProduct.get(id) });
                    remaining -= take;
                }
            }
        } finally {
            this._applyingPromotionPacks = false;
        }
    },

    /** Packs de la sucursal de la caja vigentes hoy. */
    _getActivePromotionPacks() {
        const companyId = this.company_id?.id ?? this.config?.company_id?.id;
        const today = this._getPromotionToday();
        return this.getPromotionPacks()
            .filter((pack) => companyId && (pack.data.companies || []).includes(companyId))
            .filter((pack) => (!pack.data.date_start || pack.data.date_start <= today) &&
                (!pack.data.date_end || today <= pack.data.date_end));
    },

    /**
     * Promociones arrancadas pero incompletas: la orden tiene unidades de algún producto del
     * pack que quedaron fuera de los packs ya aplicados, y falta algo para completar otro.
     * La que más ahorra primero (las más caras que los sueltos al final), sin las
     * descartadas, hasta 3.
     * Lee el estado ya aplicado: no recalcula los packs.
     */
    getPromotionHints() {
        if (this.finalized) {
            return [];
        }
        const leftover = new Map();
        const unitPrice = new Map();
        for (const line of this.get_orderlines()) {
            if (!this._isPromotionPackCandidate(line) || line.promotion_pack_tmpl_id) {
                continue;
            }
            const id = line.product_id.id;
            leftover.set(id, (leftover.get(id) || 0) + line.get_quantity());
            if (!unitPrice.has(id)) {
                unitPrice.set(id, line.get_unit_price());
            }
        }
        if (!leftover.size) {
            return [];
        }
        const dismissed = this.uiState.dismissedPromotionHints || [];
        const hints = [];
        for (const pack of this._getActivePromotionPacks()) {
            const tmplId = recordId(pack.template);
            if (dismissed.includes(tmplId) || !pack.components.some((c) => leftover.get(c.product.id) > 0)) {
                continue;
            }
            const missing = pack.components
                .filter((c) => (leftover.get(c.product.id) || 0) < c.qty)
                .map((c) => ({ product: c.product, qty: c.qty - (leftover.get(c.product.id) || 0) }));
            if (!missing.length) {
                continue;
            }
            const regular = pack.components.reduce((acc, c) => {
                const price = unitPrice.has(c.product.id)
                    ? unitPrice.get(c.product.id)
                    : c.product.get_price(this.pricelist_id, c.qty);
                return acc + price * c.qty;
            }, 0);
            if (!Number.isFinite(regular) || regular <= 0) {
                continue;
            }
            const price = this._getPromotionPackPrice(pack, regular);
            const saving = regular - price;
            // Igual que applyPromotionPacks: una promo más cara que los sueltos también se
            // sugiere (saving negativo, va al final); una que cuesta lo mismo no cambia nada.
            if (!(price > 0) || !Number.isFinite(saving) || saving === 0) {
                continue;
            }
            hints.push({
                tmplId, name: pack.product.display_name, product: pack.product,
                components: pack.components, missing, price, regular, saving,
            });
        }
        return hints.sort((a, b) => b.saving - a.saving).slice(0, 3);
    },

    /**
     * Promos ya aplicadas en la orden: [{tmplId, name, product, times, saving}]. El ahorro
     * es el descuento puesto en sus líneas (una promo más cara sube el precio: ahorro 0).
     */
    getAppliedPromotions() {
        const byTmpl = new Map();
        for (const line of this.get_orderlines()) {
            const tmplId = recordId(line.promotion_pack_tmpl_id);
            if (!tmplId) {
                continue;
            }
            const entry = byTmpl.get(tmplId) || { units: new Map(), saving: 0 };
            const id = line.product_id.id;
            entry.units.set(id, (entry.units.get(id) || 0) + line.get_quantity());
            entry.saving += line.get_unit_price() * line.get_quantity() * (line.get_discount() || 0) / 100;
            byTmpl.set(tmplId, entry);
        }
        const applied = [];
        for (const pack of this.getPromotionPacks()) {
            const tmplId = recordId(pack.template);
            const entry = byTmpl.get(tmplId);
            if (!entry) {
                continue;
            }
            const times = Math.min(...pack.components.map((c) => Math.floor((entry.units.get(c.product.id) || 0) / c.qty)));
            applied.push({ tmplId, name: pack.product.display_name, product: pack.product, times, saving: entry.saving });
        }
        return applied;
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
    /** Un descuento o precio puesto a mano (fuera del recálculo) saca la línea de la
     *  promoción: el cajero decidió el precio y los controles de motivo lo tienen que ver. */
    _dropPromotionOnManualChange() {
        if (this.promotion_pack_tmpl_id && !this.order_id?._applyingPromotionPacks) {
            this.update({ promotion_pack_tmpl_id: false });
        }
    },

    set_discount(discount) {
        const res = super.set_discount(...arguments);
        this._dropPromotionOnManualChange();
        return res;
    },

    set_unit_price(price) {
        const res = super.set_unit_price(...arguments);
        this._dropPromotionOnManualChange();
        return res;
    },

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
        // Vuelve a mostrar el texto de las promos que toca el producto recién agregado.
        const collapsed = order.uiState.collapsedPromotionHints;
        if (collapsed?.length) {
            const touched = order.getPromotionHints()
                .filter((hint) => hint.components.some((c) => c.product.id === product?.id))
                .map((hint) => hint.tmplId);
            if (touched.length) {
                order.uiState.collapsedPromotionHints = collapsed.filter((id) => !touched.includes(id));
            }
        }
        return line;
    },
});
