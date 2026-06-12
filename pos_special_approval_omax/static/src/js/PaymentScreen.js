/** @odoo-module **/

import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { patch } from "@web/core/utils/patch";
import { ValidationService } from './ValidationService';
import { _t } from "@web/core/l10n/translation";

patch(PaymentScreen.prototype, {

    setup() {
        super.setup();
        this.validationService = new ValidationService(this.env);
    },

    async addNewPaymentLine(paymentMethod) {
        try {
            let validated_payment_method_ids = [];
            this.pos.config.validated_payment_method_ids.forEach(method => {
               validated_payment_method_ids.push(method.id);
            });
            if (validated_payment_method_ids.includes(paymentMethod.id)) {
                const validationRequired = this.validationService.isValidationRequired('payment_method');
                
                if (validationRequired) {
                    const validationSuccess = await this.validationService.validateOperation(
                        'payment_method', 
                        _t(paymentMethod.name + " Payment Method - Manager Validation Required")
                    );
                    
                    if (!validationSuccess) {
                        return false;
                    }
                }
            }

            return super.addNewPaymentLine(paymentMethod);
        } catch (error) {
            console.error('Error in validation:', error);
            return super.addNewPaymentLine(paymentMethod);
        }
    },

    async updateSelectedPaymentline(amount = false) {
        try{
            let validated_payment_method_ids = [];
            this.pos.config.validated_payment_method_ids.forEach(method => {
               validated_payment_method_ids.push(method.id);
            });
            if (this.paymentLines.every((line) => line.paid)) {
                if(validated_payment_method_ids.includes(this.payment_methods_from_config[0].id)) {
                    const validationRequired = this.validationService.isValidationRequired('payment_method');
                
                    if (validationRequired) {
                        const validationSuccess = await this.validationService.validateOperation(
                            'payment_method', 
                            _t(this.payment_methods_from_config[0].name + " Payment Method - Manager Validation Required")
                        );
                        
                        if (!validationSuccess) {
                            this.numberBuffer.reset();
                            return false;
                        }
                    }
                }
            }
            return super.updateSelectedPaymentline(amount);
        } catch (error) {
            console.error('Error in validation:', error);
            return super.updateSelectedPaymentline(amount);
        }

    }
});