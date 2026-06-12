/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";

// El patch de deletePaymentLine fue migrado de forma más robusta a PosOrder.remove_paymentline en pos_order_patch.js
// para asegurar la ejecución ante cualquier método de eliminación (incluido teclado numérico / backspace).
