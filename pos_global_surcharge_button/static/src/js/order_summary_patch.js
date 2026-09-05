/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";

patch(OrderSummary.prototype, {
    /** Guard para un bug del Odoo 18 base que corta el POS justo en el flujo de
     *  devolver un recargo (agregar el producto Recargo, click en la línea, `-`).
     *
     *  `clickLine` deselecciona la línea cuando se hace click sobre la que ya
     *  estaba seleccionada: programa un timeout de 300 ms que pone
     *  `selected_orderline_uuid = null`. Como al agregar un producto queda
     *  auto-seleccionado, el primer click del cajero ya cae en esa rama y el
     *  pedido queda sin línea seleccionada. Después, `_handleNegationOnFirstInput`
     *  lee `selectedLine.refunded_orderline_id` sin comprobar que exista y tira
     *  `TypeError: Cannot read properties of undefined`.
     *
     *  El llamador (`updateSelectedOrderline`) ya trata `selectedLine` como
     *  opcional en todo lo que sigue, así que devolver el buffer sin tocar es el
     *  comportamiento correcto: la tecla simplemente no aplica a ninguna línea. */
    _handleNegationOnFirstInput(buffer, key, selectedLine) {
        if (!selectedLine) {
            return buffer;
        }
        return super._handleNegationOnFirstInput(buffer, key, selectedLine);
    },
});
