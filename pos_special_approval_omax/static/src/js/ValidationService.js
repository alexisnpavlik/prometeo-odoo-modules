/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

// Import popup components
import { ValidationMethodPopup } from './ValidationMethodPopup';
import { BarcodeValidationPopup } from './BarcodeValidationPopup';
import { PasswordValidationPopup } from './PasswordValidationPopup';
import { PinValidationPopup } from './PinValidationPopup';
import { WrongValidationPopup } from './WrongValidationPopup';

export class ValidationService {

    constructor(env) {
        this.env = env;
        this.dialog = env.services.dialog;
    }
    
    /**
     * Check if manager validation is required for an operation
     */
    isValidationRequired(operation) {
        const pos = this.env.services.pos;
        let validationEnabledUsers = [];
        pos.config.manager_ids.forEach(user => {
            validationEnabledUsers.push(user.id)
        });
        if (!pos.config.manager_validation || !validationEnabledUsers.includes(pos.user.id)) {
            return false;
        }

        const validationMap = {
            'add_product_to_order': pos.config.validate_add_product_to_order,
            'order_line_deletion': pos.config.validate_order_line_deletion,
            'order_deletion': pos.config.validate_order_deletion,
            'apply_discount': pos.config.validate_apply_discount,
            'price_change': pos.config.validate_price_change,
            'quantity_change': pos.config.validate_quantity_change,
            'payment': pos.config.validate_payment,
            'refund': pos.config.validate_refund,
            'cash_move': pos.config.validate_cash_move,
            'payment_method': pos.config.validate_payment_methods,
            'global_discount': pos.config.validate_global_discount,
            'open_session': pos.config.validate_open_session,
            'close_session': pos.config.validate_close_session,
        };

        return validationMap[operation] || false;
    }

    /**
     * Check if user is already validated for current order (one-time password)
     */
    isUserValidatedForOrder(userId, order = null) {
        const config = this.env.services.pos.config;
        if (!config.one_time_password) {
            return false;
        }

        const currentOrder = order || this.env.services.pos.get_order();
        if (!currentOrder) {
            return false;
        }

        // Initialize validated_users array if it doesn't exist
        if (!currentOrder.validated_users) {
            currentOrder.validated_users = [];
        }

        return currentOrder.validated_users.includes(userId);
    }

    /**
     * Mark user as validated for current order
     */
    markUserValidatedForOrder(userId, order = null) {
        const config = this.env.services.pos.config;
        if (!config.one_time_password) {
            return;
        }

        const currentOrder = order || this.env.services.pos.get_order();
        if (!currentOrder) {
            return;
        }

        // Initialize validated_users array if it doesn't exist
        if (!currentOrder.validated_users) {
            currentOrder.validated_users = [];
        }

        // Add user to validated list if not already present
        if (!currentOrder.validated_users.includes(userId)) {
            currentOrder.validated_users.push(userId);
        }

    }

    /**
     * Clear validated users for an order (when order is deleted/completed)
     */
    clearOrderValidation(order = null) {
        const currentOrder = order || this.env.services.pos.get_order();
        if (currentOrder && currentOrder.validated_users) {
            currentOrder.validated_users = [];
        }
    }

    /**
     * Get available validation methods based on configuration
     */
    getAvailableValidationMethods() {
        const config = this.env.services.pos.config;
        const validationType = config.validation_type || 'all';
        const methods = [];

        switch(validationType) {
            case 'all':
                methods.push('barcode', 'password', 'pin');
                break;
            case 'barcode':
                methods.push('barcode');
                break;
            case 'password':
                methods.push('password');
                break;
            case 'pin':
                methods.push('pin');
                break;
            case 'pin_password':
                methods.push('password', 'pin');
                break;
            case 'pin_barcode':
                methods.push('barcode', 'pin');
                break;
            case 'password_barcode':
                methods.push('barcode', 'password');
                break;
        }

        return methods;
    }

    /**
     * Main validation method - handles the entire validation flow
     */
    async validateOperation(operation, title = null) {
        try {
            const pos = this.env.services.pos;
            
            // First check if user is already validated for current order (one-time password)
            if (pos.config.one_time_password) {
                const isUserValidated = this.isUserValidatedForOrder(pos.user.id);
                if (isUserValidated) {
                    return true;
                }
            }

            // Check if validation is required
            if (!this.isValidationRequired(operation)) {
                return true;
            }

            const displayTitle = title || _t("Manager Validation Required");
            const availableMethods = this.getAvailableValidationMethods();

            // If only one method available, skip method selection
            let selectedMethod;
            if (availableMethods.length === 1) {
                selectedMethod = availableMethods[0];
            } else {
                // Show method selection popup
                selectedMethod = await this.showValidationMethodPopup(displayTitle);
                if (!selectedMethod) {
                    return false; // User cancelled
                }
            }

            // Get credentials based on selected method
            const credentials = await this.getCredentials(selectedMethod, displayTitle);
            if (!credentials) {
                return false; // User cancelled
            }

            // Validate credentials
            const validationResult = await this.validateCredentials(credentials);
            if (validationResult.success) {
                // Mark user as validated for current order if one-time password is enabled
                this.markUserValidatedForOrder(validationResult.userId);
                return true;
            } else {
                await this.showWrongValidationPopup(validationResult.message);
                return false;
            }

        } catch (error) {
            console.error('Validation error:', error);
            await this.showWrongValidationPopup(_t("An error occurred during validation. Please try again."));
            return false;
        }
    }

    /**
     * Show validation method selection popup
     */
    async showValidationMethodPopup(title) {
        return new Promise((resolve) => {
            this.dialog.add(ValidationMethodPopup, {
                title: title,
                getPayload: (result) => {
                    resolve(result ? result.method : null);
                },
                close: () => resolve(null)
            });
        });
    }

    /**
     * Get credentials based on selected method
     */
    async getCredentials(method, title) {
        switch(method) {
            case 'barcode':
                return await this.showBarcodeValidationPopup(title);
            case 'password':
                return await this.showPasswordValidationPopup(title);
            case 'pin':
                return await this.showPinValidationPopup(title);
            default:
                return null;
        }
    }

    /**
     * Show barcode validation popup
     */
    async showBarcodeValidationPopup(title) {
        return new Promise((resolve) => {
            this.dialog.add(BarcodeValidationPopup, {
                title: title,
                getPayload: resolve,
                close: () => resolve(null)
            });
        });
    }

    /**
     * Show password validation popup
     */
    async showPasswordValidationPopup(title) {
        return new Promise((resolve) => {
            this.dialog.add(PasswordValidationPopup, {
                title: title,
                getPayload: resolve,
                close: () => resolve(null)
            });
        });
    }

    /**
     * Show PIN validation popup
     */
    async showPinValidationPopup(title) {
        return new Promise((resolve) => {
            this.dialog.add(PinValidationPopup, {
                title: title,
                getPayload: resolve,
                close: () => resolve(null)
            });
        });
    }

    /**
     * Show wrong validation popup
     */
    async showWrongValidationPopup(message) {
        return new Promise((resolve) => {
            this.dialog.add(WrongValidationPopup, {
                title: _t("Validation Failed"),
                message: message,
                getPayload: resolve,
                close: () => resolve(false)
            });
        });
    }

    /**
     * Validate credentials against manager users
     */
    async validateCredentials(credentials) {
        try {
            const config = this.env.services.pos.config;
            const managerIds = config.manager_ids || [];
            
            if (!managerIds.length) {
                return {
                    success: false,
                    message: _t("No managers configured for validation.")
                };
            }
            let manager_ids = [];
            managerIds.forEach(manager => {
                manager_ids.push(manager.id)
            });

            const result = await rpc('/pos/validate_manager_credentials', {
                manager_ids: manager_ids,
                credentials: credentials
            });

            if (result.success) {
                return {
                    success: true,
                    userId: result.user_id,
                    message: _t("Validation successful.")
                };
            } else {
                return {
                    success: false,
                    message: result.message || _t("Invalid credentials. Please check your barcode, password, or PIN and try again.")
                };
            }

        } catch (error) {
            console.error('Credential validation error:', error);
            return {
                success: false,
                message: _t("An error occurred during validation. Please try again.")
            };
        }
    }

    /**
     * Quick validation check for users already validated in current order
     */
    async quickValidate(operation, userId = null) {
        const pos = this.env.services.pos;
        
        // First check if user is already validated for current order (one-time password)
        if (pos.config.one_time_password) {
            const currentUserId = userId || pos.user.id;
            if (this.isUserValidatedForOrder(currentUserId)) {
                return true;
            }
        }
        
        // If not validated via one-time password, check if validation is required
        if (!this.isValidationRequired(operation)) {
            return true;
        }
        
        return false;
    }
}
