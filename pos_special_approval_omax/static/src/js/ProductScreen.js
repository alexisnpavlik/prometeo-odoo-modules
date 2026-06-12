/** @odoo-module **/

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";
import { ValidationService } from './ValidationService';
import { _t } from "@web/core/l10n/translation";

patch(ProductScreen.prototype, {

    setup() {
        super.setup(...arguments);
        this.validationService = new ValidationService(this.env);
    },

    async onNumpadClick(buttonValue) {
        try {
            if (buttonValue === 'discount') {
                const validationRequired = this.validationService.isValidationRequired('apply_discount');
                
                if (validationRequired) {
                    const validationSuccess = await this.validationService.validateOperation(
                        'apply_discount', 
                        _t("Apply Discount - Manager Validation Required")
                    );
                    
                    if (!validationSuccess) {
                        return false;
                    }
                }
            }
            else if (buttonValue === 'price') {
                const validationRequired = this.validationService.isValidationRequired('price_change');
                
                if (validationRequired) {
                    const validationSuccess = await this.validationService.validateOperation(
                        'price_change', 
                        _t("Price Change - Manager Validation Required")
                    );
                    
                    if (!validationSuccess) {
                        return false;
                    }
                }
            }

            return super.onNumpadClick(buttonValue);
        } catch (error) {
            console.error('Error in validation:', error);
            return super.onNumpadClick(buttonValue);
        }
    },

    async addProductToOrder(product) {
        try {
            const validationRequired = this.validationService.isValidationRequired('add_product_to_order');
            
            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'add_product_to_order', 
                    _t("Add Product to Order - Manager Validation Required")
                );
                
                if (!validationSuccess) {
                    return false;
                }
            }

            return super.addProductToOrder(product);
        } catch (error) {
            console.error('Error in validation:', error);
            return super.addProductToOrder(product);
        }
    }
});