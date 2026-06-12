/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { usePos } from '@point_of_sale/app/store/pos_hook';
import { _t } from "@web/core/l10n/translation";

export class PinValidationPopup extends Component {
    static components = { Dialog };
    static template = "pos_special_approval_omax.PinValidationPopup";
    static props = ["close", "getPayload", "title"];

    setup() {
        this.pos = usePos();
        this.state = useState({
            pin: "",
            showPin: false,
        });
        this.inputRef = useRef("pinInput");

        this._boundHandleKeyDown = this.handleKeyDown.bind(this);

        onMounted(() => {
            document.addEventListener('keydown', this._boundHandleKeyDown);
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
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
        } else if (event.key === 'Enter' && this.state.pin.trim()) {
            event.preventDefault();
            this.confirm();
        } else if (['Backspace', 'Delete', 'ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) {
            return;
        }
        // Only allow numbers for PIN
        else if (!/[\d\b\r\n\t]/.test(event.key) && !event.ctrlKey && !event.metaKey) {
            event.preventDefault();
        }
    }

    onPinInput(ev) {
        // Only allow digits
        const value = ev.target.value.replace(/\D/g, '');
        this.state.pin = value;
        ev.target.value = value;
    }

    onNumberPadPress(number) {
        if (number === 'clear') {
            this.state.pin = '';
        } else if (number === 'backspace') {
            this.state.pin = this.state.pin.slice(0, -1);
        } else if (number === 'enter') {
            this.confirm();
        } else {
            if (this.inputRef.el.value.length >= 10) {
                return;
            }
            this.state.pin += number.toString();
        }
        // Update the actual input field
        if (this.inputRef.el) {
            this.inputRef.el.value = this.state.pin;
        }
    }

    togglePinVisibility() {
        this.state.showPin = !this.state.showPin;
    }

    get numberPadKeys() {
        return [
            [
                { key: 1, display: '1', class: 'btn-outline-primary' },
                { key: 2, display: '2', class: 'btn-outline-primary' },
                { key: 3, display: '3', class: 'btn-outline-primary' }
            ],
            [
                { key: 4, display: '4', class: 'btn-outline-primary' },
                { key: 5, display: '5', class: 'btn-outline-primary' },
                { key: 6, display: '6', class: 'btn-outline-primary' }
            ],
            [
                { key: 7, display: '7', class: 'btn-outline-primary' },
                { key: 8, display: '8', class: 'btn-outline-primary' },
                { key: 9, display: '9', class: 'btn-outline-primary' }
            ],
            [
                { key: 'clear', display: 'Clear', class: 'btn-outline-danger clear-key' },
                { key: 0, display: '0', class: 'btn-outline-primary zero-key' },
                { key: 'backspace', display: '⌫', class: 'btn-warning backspace-key' }
            ],
            [
                { key: 'enter', display: 'Enter', class: 'btn-success enter-key full-width' }
            ]
        ];
    }

    async confirm() {
        if (!this.state.pin.trim()) {
            return;
        }

        this.props.getPayload({
            pin: this.state.pin.trim()
        });
        this.props.close();
    }

    cancel() {
        this.props.getPayload(null);
        this.props.close();
    }
}