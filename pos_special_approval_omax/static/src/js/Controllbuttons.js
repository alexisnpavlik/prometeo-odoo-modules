/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { patch } from "@web/core/utils/patch";
import { ValidationService } from './ValidationService';

patch(ControlButtons.prototype, {

    setup() {
        super.setup(...arguments);
        this.validationService = new ValidationService(this.env);
    },

    async clickDiscount() {
        const validationRequired =
            this.validationService.isValidationRequired("global_discount");

        if (validationRequired) {
            const validationSuccess =
                await this.validationService.validateOperation(
                    "global_discount",
                    _t("Global Discount - Manager Validation Required")
                );

            if (!validationSuccess) {
                return;
            }
        }
        return super.clickDiscount();
    },
});