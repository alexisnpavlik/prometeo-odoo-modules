/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { usePos } from '@point_of_sale/app/store/pos_hook';
import { _t } from "@web/core/l10n/translation";

export class ValidationMethodPopup extends Component {
    static components = { Dialog };
    static template = "pos_special_approval_omax.ValidationMethodPopup";
    static props = ["close", "getPayload", "title"];

    setup() {
        this.pos = usePos();
        this.state = useState({
            selectedMethod: null,
        });

        this._boundHandleKeyDown = this.handleKeyDown.bind(this);

        onMounted(() => {
            document.addEventListener('keydown', this._boundHandleKeyDown);
        });
        
        onWillUnmount(() => {
            document.removeEventListener('keydown', this._boundHandleKeyDown);
        });
    }
    
    handleKeyDown(event) {
        if (event.key === 'Escape' && !this.isResolved) {
            event.preventDefault();
            event.stopPropagation();
            this.cancel();
        }
    }

    get validationMethods() {
        const validationType = this.pos.config.pos_validation_type || 'all';
        const methods = [];
        
        switch(validationType) {
            case 'all':
                methods.push(
                    { key: 'barcode', label: _t('Barcode'), icon: 'fa-barcode' },
                    { key: 'password', label: _t('Password'), icon: 'fa-lock' },
                    { key: 'pin', label: _t('PIN'), icon: 'fa-key' }
                );
                break;
            case 'barcode':
                methods.push({ key: 'barcode', label: _t('Barcode'), icon: 'fa-barcode' });
                break;
            case 'password':
                methods.push({ key: 'password', label: _t('Password'), icon: 'fa-lock' });
                break;
            case 'pin':
                methods.push({ key: 'pin', label: _t('PIN'), icon: 'fa-key' });
                break;
            case 'pin_password':
                methods.push(
                    { key: 'password', label: _t('Password'), icon: 'fa-lock' },
                    { key: 'pin', label: _t('PIN'), icon: 'fa-key' }
                );
                break;
            case 'pin_barcode':
                methods.push(
                    { key: 'barcode', label: _t('Barcode'), icon: 'fa-barcode' },
                    { key: 'pin', label: _t('PIN'), icon: 'fa-key' }
                );
                break;
            case 'password_barcode':
                methods.push(
                    { key: 'barcode', label: _t('Barcode'), icon: 'fa-barcode' },
                    { key: 'password', label: _t('Password'), icon: 'fa-lock' }
                );
                break;
        }
        
        return methods;
    }

    selectMethod(method) {
        this.state.selectedMethod = method.key;
        this.props.getPayload({ method: method.key });
        this.props.close();
    }

    cancel() {
        this.props.getPayload(null);
        this.props.close();
    }
}