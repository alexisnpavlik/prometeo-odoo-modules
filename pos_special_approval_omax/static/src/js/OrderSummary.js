/** @odoo-module **/

import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { patch } from "@web/core/utils/patch";
import { ValidationService } from './ValidationService';
import { _t } from "@web/core/l10n/translation";

patch(OrderSummary.prototype, {

    setup() {
        try {
            super.setup(...arguments);
            this.validationService = new ValidationService(this.env);
        }
        catch (error) {
            console.error('Error in setup:', error);
            return super.setup(...arguments);
        }
    },

    async _setValue(val) {
        try {
            const { numpadMode } = this.pos;
            let selectedLine = this.currentOrder.get_selected_orderline();
            if (selectedLine && numpadMode === "quantity") {
                if (val === "remove") {
                    const validationRequired = this.validationService.isValidationRequired('order_line_deletion');
                    
                    if (validationRequired) {
                        const validationSuccess = await this.validationService.validateOperation(
                            'order_line_deletion', 
                            _t("Remove Order Line - Manager Validation Required")
                        );
                        
                        if (!validationSuccess) {
                            return false;
                        }
                    }
                } else {
                    const validationRequired = this.validationService.isValidationRequired('quantity_change');
                    
                    if (validationRequired) {
                        const validationSuccess = await this.validationService.validateOperation(
                            'quantity_change', 
                            _t("Quantity Change - Manager Validation Required")
                        );
                        
                        if (!validationSuccess) {
                            this.numberBuffer.reset();
                            return false;
                        }
                    }
                }
            }
            return super._setValue(val);
        } catch (error) {
            console.error('Error in validation:', error);
            return super._setValue(val);
        }
    }
});