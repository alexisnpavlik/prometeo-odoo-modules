/** @odoo-module **/

import { OpeningControlPopup } from "@point_of_sale/app/store/opening_control_popup/opening_control_popup";
import { patch } from "@web/core/utils/patch";
import { ValidationService } from './ValidationService';
import { _t } from "@web/core/l10n/translation";

patch(OpeningControlPopup.prototype, {

    setup() {
        super.setup(...arguments);
        this.validationService = new ValidationService(this.env);
    },

    async confirm() {
        try {
            const validationRequired = this.validationService.isValidationRequired('open_session');

            if (validationRequired) {
                const validationSuccess = await this.validationService.validateOperation(
                    'open_session',
                    _t("Open Session - Manager Validation Required")
                );

                if (!validationSuccess) {
                    return;
                }
            }
            return super.confirm(...arguments);
        } catch (error) {
            console.error('Error in validation:', error);
            return super.confirm(...arguments);
        }
    }
});
