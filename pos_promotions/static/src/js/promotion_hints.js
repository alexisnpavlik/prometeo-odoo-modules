/** @odoo-module **/

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";

/**
 * Burbujas flotantes con las promos que la orden arrancó y no completó, una fila por promo
 * (texto a la izquierda, círculo a la derecha). Solo informan: tocar un círculo oculta o
 * muestra su texto, la ✕ la descarta para esta orden.
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

    get applied() {
        return this.order?.getAppliedPromotions() || [];
    }

    /** Clave para ocultar el texto: las aplicadas van aparte de las pendientes de la misma promo. */
    appliedKey(promo) {
        return `applied-${promo.tmplId}`;
    }

    isAppliedCollapsed(promo) {
        return (this.order?.uiState.collapsedPromotionHints || []).includes(this.appliedKey(promo));
    }

    onClickAppliedDot(promo) {
        this._toggleCollapsed(this.appliedKey(promo));
    }

    /** Promo con el texto oculto (el cajero tocó su círculo para destapar productos). */
    isCollapsed(hint) {
        return (this.order?.uiState.collapsedPromotionHints || []).includes(hint.tmplId);
    }

    imageUrl(hint) {
        return hint.missing[0].product.getImageUrl();
    }

    /** Dos primeras letras o dígitos del producto que falta: "Coca-Cola" → "CO". */
    initials(hint) {
        const name = hint.missing[0].product.display_name || "";
        return (name.match(/[\p{L}\p{N}]/gu) || []).slice(0, 2).join("").toUpperCase();
    }

    /** Una línea por producto que falta: "+ 1 Escritorio personalizable" (sin la variante). */
    missingText({ product, qty }) {
        return `+ ${qty} ${product.name || product.display_name}`;
    }

    formatCurrency(amount) {
        return this.env.utils.formatCurrency(amount);
    }

    /** Oculta o muestra el texto de la promo (no la descarta). */
    onClickDot(hint) {
        this._toggleCollapsed(hint.tmplId);
    }

    _toggleCollapsed(key) {
        const uiState = this.order.uiState;
        const collapsed = uiState.collapsedPromotionHints || [];
        uiState.collapsedPromotionHints = collapsed.includes(key)
            ? collapsed.filter((id) => id !== key)
            : [...collapsed, key];
    }

    onClose(hint) {
        const uiState = this.order.uiState;
        uiState.dismissedPromotionHints = [...(uiState.dismissedPromotionHints || []), hint.tmplId];
    }
}
