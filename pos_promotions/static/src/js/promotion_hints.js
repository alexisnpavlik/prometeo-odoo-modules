/** @odoo-module **/

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";

/**
 * Burbujas flotantes con las promos que la orden arrancó y no completó. Solo informan:
 * tocar un círculo abre su burbuja, la ✕ la descarta para esta orden.
 */
export class PromotionHints extends Component {
    static template = "pos_promotions.PromotionHints";
    static props = {};

    setup() {
        this.pos = usePos();
    }

    get order() {
        return this.pos.get_order();
    }

    get hints() {
        return this.order?.getPromotionHints() || [];
    }

    /** La burbuja abierta, dentro de los hints ya calculados en este render. */
    openHint(hints) {
        const openId = this.order?.uiState.openPromotionHintTmplId;
        return hints.find((hint) => hint.tmplId === openId);
    }

    imageUrl(hint) {
        return hint.missing[0].product.getImageUrl();
    }

    /** Dos primeras letras o dígitos del producto que falta: "Coca-Cola" → "CO". */
    initials(hint) {
        const name = hint.missing[0].product.display_name || "";
        return (name.match(/[\p{L}\p{N}]/gu) || []).slice(0, 2).join("").toUpperCase();
    }

    /** "Sumá 1 Vaso más" si ya hay de ese producto; si no, "Sumá 1 Coca-Cola y 2 Hielo". */
    missingText(hint) {
        const lines = this.order.get_orderlines();
        const parts = hint.missing.map(({ product, qty }) => {
            const more = lines.some((line) => line.product_id.id === product.id) ? " más" : "";
            return `${qty} ${product.display_name}${more}`;
        });
        return `Sumá ${parts.join(" y ")}`;
    }

    formatCurrency(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    /** Abre la burbuja del círculo; si ya estaba abierta, la cierra (sin descartar la promo). */
    onClickDot(hint) {
        const uiState = this.order.uiState;
        uiState.openPromotionHintTmplId = uiState.openPromotionHintTmplId === hint.tmplId ? false : hint.tmplId;
    }

    onClose(hint) {
        const uiState = this.order.uiState;
        uiState.dismissedPromotionHints = [...(uiState.dismissedPromotionHints || []), hint.tmplId];
        if (uiState.openPromotionHintTmplId === hint.tmplId) {
            uiState.openPromotionHintTmplId = false;
        }
    }
}
