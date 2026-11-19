/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";

// Import popup components
import { ValidationMethodPopup } from './ValidationMethodPopup';
import { BarcodeValidationPopup } from './BarcodeValidationPopup';
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
        if (!pos.config.manager_validation || this.isUserExcluded()) {
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
     * True si el usuario logueado está en los excluidos de autorización de la caja
     */
    isUserExcluded() {
        const pos = this.env.services.pos;
        const excluded = pos.config.excluded_user_ids || [];
        return excluded.some((user) => (user?.id ?? user) === pos.user.id);
    }

    /**
     * True si el pedido ya fue autorizado (autorización única por pedido)
     */
    isOrderApproved(order = null) {
        if (!this.env.services.pos.config.one_time_password) {
            return false;
        }
        const currentOrder = order || this.env.services.pos.get_order();
        return Boolean(currentOrder && currentOrder.approval_granted);
    }

    /**
     * Marca el pedido como autorizado (autorización única por pedido)
     */
    markOrderApproved(order = null) {
        if (!this.env.services.pos.config.one_time_password) {
            return;
        }
        const currentOrder = order || this.env.services.pos.get_order();
        if (currentOrder) {
            currentOrder.approval_granted = true;
        }
    }

    /**
     * Clear validated users for an order (when order is deleted/completed)
     */
    clearOrderValidation(order = null) {
        const currentOrder = order || this.env.services.pos.get_order();
        if (currentOrder) {
            currentOrder.approval_granted = false;
        }
    }

    /**
     * Get available validation methods based on configuration
     */
    getAvailableValidationMethods() {
        const config = this.env.services.pos.config;
        const validationType = config.validation_type || 'all';
        const methods = [];
        if (['all', 'barcode'].includes(validationType) && config.has_approval_barcode) {
            methods.push('barcode');
        }
        if (['all', 'pin'].includes(validationType) && config.has_approval_pin) {
            methods.push('pin');
        }
        return methods;
    }

    /**
     * Main validation method - handles the entire validation flow
     */
    async validateOperation(operation, title = null) {
        try {
            const pos = this.env.services.pos;
            
            // Pedido ya autorizado (autorización única por pedido)
            if (this.isOrderApproved()) {
                return true;
            }

            // Check if validation is required
            if (!this.isValidationRequired(operation)) {
                return true;
            }

            const displayTitle = title || _t("Manager Validation Required");
            const availableMethods = this.getAvailableValidationMethods();

            // Caja sin credenciales: se bloquea la operación
            if (!availableMethods.length) {
                await this.showWrongValidationPopup(
                    _t("Esta caja no tiene PIN ni código de autorización configurado. Pedile a un administrador que lo cargue en la configuración del punto de venta.")
                );
                return false;
            }

            // If only one method available, skip method selection
            let selectedMethod;
            if (availableMethods.length === 1) {
                selectedMethod = availableMethods[0];
            } else {
                // Show method selection popup
                selectedMethod = await this.showValidationMethodPopup(displayTitle, availableMethods);
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
            const validationResult = await this.validateCredentials(credentials, operation);
            if (validationResult.success) {
                this.markOrderApproved();
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
    async showValidationMethodPopup(title, methods) {
        return new Promise((resolve) => {
            this.dialog.add(ValidationMethodPopup, {
                title: title,
                methods: methods,
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
     * Valida la credencial contra la caja en el servidor (y queda registrada)
     */
    async validateCredentials(credentials, operation = null) {
        try {
            const pos = this.env.services.pos;
            const order = pos.get_order();
            const result = await rpc('/pos/validate_approval', {
                config_id: pos.config.id,
                session_id: pos.session?.id || null,
                operation: operation,
                order_reference: order?.pos_reference || order?.name || null,
                credentials: credentials,
            });
            return {
                success: Boolean(result.success),
                message: result.message || _t("Invalid credentials. Please check your barcode or PIN and try again."),
            };
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
        
        // Pedido ya autorizado (autorización única por pedido)
        if (this.isOrderApproved()) {
            return true;
        }

        // Si no está autorizado, ver si la operación requiere autorización
        if (!this.isValidationRequired(operation)) {
            return true;
        }
        
        return false;
    }
}
