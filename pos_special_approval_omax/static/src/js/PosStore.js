/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ValidationService } from './ValidationService';
import { _t } from "@web/core/l10n/translation";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this.validationService = new ValidationService(this.env);
    },

    /**
     * Override the onDeleteOrder method to add validation
     */
    async onDeleteOrder(order) {
        try {
            const validationRequired = this.validationService.isValidationRequired('order_deletion');
            
            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'order_deletion', 
                    _t("Delete Order - Manager Validation Required")
                );
                
                if (!validationSuccess) {
                    return false;
                }
            }
            return super.onDeleteOrder(order);

        } catch (error) {
            console.error('Error in validation:', error);
            return super.onDeleteOrder(order);
        }
    },

    async pay() {
        try {
            const validationRequired = this.validationService.isValidationRequired('payment');
            
            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'payment', 
                    _t("Payment - Manager Validation Required")
                );
                
                if (!validationSuccess) {
                    return false;
                }
            }
            return super.pay();
        } catch (error) {
            console.error('Error in validation:', error);
            return super.pay();
        }
    },

    async cashMove() {
        try {
            const validationRequired = this.validationService.isValidationRequired('cash_move');

            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'cash_move',
                    _t("Cash Move - Manager Validation Required")
                );

                if (!validationSuccess) {
                    return false;
                }
            }
            return super.cashMove();
        } catch (error) {
            console.error('Error in validation:', error);
            return super.cashMove();
        }
    },

    async closeSession() {
        try {
            const validationRequired = this.validationService.isValidationRequired('close_session');

            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'close_session',
                    _t("Close Session - Manager Validation Required")
                );

                if (!validationSuccess) {
                    return false;
                }
            }
            return super.closeSession(...arguments);
        } catch (error) {
            console.error('Error in validation:', error);
            return super.closeSession(...arguments);
        }
    }
});