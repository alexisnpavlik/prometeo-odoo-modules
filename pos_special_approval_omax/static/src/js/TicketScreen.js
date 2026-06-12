/** @odoo-module **/

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";
import { ValidationService } from './ValidationService';
import { _t } from "@web/core/l10n/translation";

patch(TicketScreen.prototype, {

    setup() {
        super.setup();
        this.validationService = new ValidationService(this.env);
    },

    async onDoRefund() {
        try {
            const validationRequired = this.validationService.isValidationRequired('refund');
            
            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'refund', 
                    _t("Refund - Manager Validation Required")
                );
                
                if (!validationSuccess) {
                    return false;
                }
            }
            return super.onDoRefund();
        } catch (error) {
            console.error('Error in validation:', error);
            return super.onDoRefund();
        }
    }
});