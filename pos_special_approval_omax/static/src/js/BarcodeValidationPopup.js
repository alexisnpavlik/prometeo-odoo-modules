/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount, useRef } from '@odoo/owl';
import { Dialog } from '@web/core/dialog/dialog';
import { usePos } from '@point_of_sale/app/store/pos_hook';
import { _t } from "@web/core/l10n/translation";
import { ValidationBarcodeScanner } from './ValidationBarcodeScanner';

export class BarcodeValidationPopup extends Component {
    static components = { Dialog, ValidationBarcodeScanner };
    static template = "pos_special_approval_omax.BarcodeValidationPopup";
    static props = ["close", "getPayload", "title"];

    setup() {
        this.pos = usePos();
        this.state = useState({
            barcode: "",
            isScanning: false,
        });
        this.inputRef = useRef("barcodeInput");

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

    onCameraScanResult(result) {
        const value = result?.text || result;

        this.state.barcode = value;
        this.sound = this.env.services["mail.sound_effects"];
        this.sound.play("beep");

        this.state.isScanning = false;

        this.confirm();
    }
    
    handleKeyDown(event) {
        if (event.key === 'Escape' && !this.isResolved) {
            event.preventDefault();
            event.stopPropagation();
            this.cancel();
        } else if (event.key === 'Enter' && this.state.barcode.trim()) {
            event.preventDefault();
            this.confirm();
        }
    }

    onBarcodeInput(ev) {
        this.state.barcode = ev.target.value;
    }

    onScanStart() {
        this.state.isScanning = true;
        if (this.inputRef.el) {
            this.inputRef.el.focus();
        }
    }

    onScanStop() {
        this.state.isScanning = false;
    }

    async confirm() {
        if (!this.state.barcode.trim()) {
            return;
        }

        this.props.getPayload({
            barcode: this.state.barcode.trim()
        });
        this.props.close();
    }

    cancel() {
        this.props.getPayload(null);
        this.props.close();
    }
}