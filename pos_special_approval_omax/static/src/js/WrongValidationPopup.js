/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { _t } from "@web/core/l10n/translation";

export class WrongValidationPopup extends Component {
    static components = { Dialog };
    static template = "pos_special_approval_omax.WrongValidationPopup";
    static props = ["close", "getPayload", "title", "message"];

    setup() {
        this.state = useState({
            countdown: 5,
        });

        this._boundHandleKeyDown = this.handleKeyDown.bind(this);
        
        onMounted(() => {
            document.addEventListener('keydown', this._boundHandleKeyDown);
            this.startCountdown();
        });
        
        onWillUnmount(() => {
            document.removeEventListener('keydown', this._boundHandleKeyDown);
            if (this.countdownInterval) {
                clearInterval(this.countdownInterval);
            }
        });
    }

    startCountdown() {
        this.countdownInterval = setInterval(() => {
            this.state.countdown--;
            if (this.state.countdown <= 0) {
                this.close();
            }
        }, 1000);
    }
    
    handleKeyDown(event) {
        if (event.key === 'Escape' || event.key === 'Enter') {
            event.preventDefault();
            event.stopPropagation();
            this.close();
        }
    }

    get displayMessage() {
        return this.props.message || _t("Invalid credentials. Please check your barcode, password, or PIN and try again.");
    }

    close() {
        if (this.countdownInterval) {
            clearInterval(this.countdownInterval);
        }
        this.props.getPayload(false);
        this.props.close();
    }
}