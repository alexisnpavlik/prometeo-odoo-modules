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
            warning: "",
        });
        this.inputRef = useRef("barcodeInput");

        // Deteccion de lector fisico por timing entre pulsaciones.
        this.MAX_GAP_MS = 50;       // gap maximo entre teclas para considerarlo lector
        this.MIN_LEN = 3;           // largo minimo de un codigo valido
        this.IDLE_COMMIT_MS = 100;  // sin teclas por este lapso -> autocommit (lectores sin Enter)
        this._buffer = [];          // [{char, t}]
        this._lastT = 0;
        this._idleTimer = null;
        this._warnTimer = null;

        this._boundHandleKeyDown = this.handleKeyDown.bind(this);

        onMounted(() => {
            document.addEventListener('keydown', this._boundHandleKeyDown);
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
        });

        onWillUnmount(() => {
            document.removeEventListener('keydown', this._boundHandleKeyDown);
            clearTimeout(this._idleTimer);
            clearTimeout(this._warnTimer);
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
            return;
        }

        if (event.key === 'Enter') {
            event.preventDefault();
            this._commitBuffer();
            return;
        }

        // Solo caracteres imprimibles; se capturan en el buffer y NO llegan al input
        // ni al lector de productos del POS.
        if (event.key.length === 1) {
            event.preventDefault();
            event.stopPropagation();

            const now = performance.now();
            // Si paso demasiado tiempo desde la ultima tecla, arranca una rafaga nueva.
            if (this._buffer.length && now - this._lastT > this.IDLE_COMMIT_MS) {
                this._buffer = [];
            }
            this._buffer.push({ char: event.key, t: now });
            this._lastT = now;

            // Autocommit para lectores que no envian sufijo Enter.
            clearTimeout(this._idleTimer);
            this._idleTimer = setTimeout(() => this._commitBuffer(), this.IDLE_COMMIT_MS);
        }
    }

    _commitBuffer() {
        clearTimeout(this._idleTimer);
        const buf = this._buffer;
        this._buffer = [];
        if (buf.length < this.MIN_LEN) {
            return; // ruido suelto, ignorar
        }
        for (let i = 1; i < buf.length; i++) {
            if (buf[i].t - buf[i - 1].t > this.MAX_GAP_MS) {
                // pausa propia de tecleo humano
                this._flashWarning(_t("Ingreso manual detectado. Usá el lector de código de barras."));
                return;
            }
        }
        this.state.barcode = buf.map((b) => b.char).join("");
        this.env.services["mail.sound_effects"].play("beep");
        this.confirm(); // autoconfirma, igual que la camara
    }

    _flashWarning(msg) {
        this.state.warning = msg;
        clearTimeout(this._warnTimer);
        this._warnTimer = setTimeout(() => (this.state.warning = ""), 2500);
    }

    blockEvent(ev) {
        ev.preventDefault();
        ev.stopPropagation();
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