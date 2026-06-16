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
        this._done = false;         // ya se confirmo/cancelo: tragar todo lo que quede

        // En modo scanner-only usamos fase de captura para adueñarnos del teclado;
        // en modo permisivo, fase de burbuja para no interferir con el tecleo manual.
        this._capture = this.scannerOnly;

        this._boundHandleKeyDown = this.handleKeyDown.bind(this);

        onMounted(() => {
            document.addEventListener('keydown', this._boundHandleKeyDown, this._capture);
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
        });

        onWillUnmount(() => {
            document.removeEventListener('keydown', this._boundHandleKeyDown, this._capture);
            clearTimeout(this._idleTimer);
            clearTimeout(this._warnTimer);
        });
    }

    /**
     * Si el POS tiene activado "Barcode Scanner Only" (default true), se bloquea el
     * tecleo manual y el pegado; solo se acepta un lector físico (detección por timing).
     */
    get scannerOnly() {
        return this.pos.config.enforce_barcode_scanner !== false;
    }

    get maskedBarcode() {
        return this.state.barcode ? "•".repeat(this.state.barcode.length) : "";
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
        // Modo permisivo (feature desactivada): comportamiento original, se permite
        // tecleo manual y pegado; solo se atajan Escape y Enter.
        if (!this.scannerOnly) {
            if (event.key === 'Escape') {
                event.preventDefault();
                this.cancel();
            } else if (event.key === 'Enter' && this.state.barcode.trim()) {
                event.preventDefault();
                this.confirm();
            }
            return;
        }

        // Una vez confirmado/cancelado, tragar cualquier tecla residual (p. ej. el
        // segundo Enter del CR+LF del lector) para que no llegue al popup siguiente.
        if (this._done) {
            event.preventDefault();
            event.stopImmediatePropagation();
            return;
        }

        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopImmediatePropagation();
            this._done = true;
            this.cancel();
            return;
        }

        // El Enter del lector NO confirma de inmediato: se traga y se reprograma el
        // commit por inactividad. Así esperamos a que el lector termine TODA su ráfaga
        // (incluido el Enter de cola) antes de cerrar, y ningún Enter se filtra al
        // NumberPopup del descuento.
        if (event.key === 'Enter') {
            event.preventDefault();
            event.stopImmediatePropagation();
            clearTimeout(this._idleTimer);
            this._idleTimer = setTimeout(() => this._commitBuffer(), this.IDLE_COMMIT_MS);
            return;
        }

        // Solo caracteres imprimibles; se capturan en el buffer y NO llegan al input
        // ni al lector de productos del POS.
        if (event.key.length === 1) {
            event.preventDefault();
            event.stopImmediatePropagation();

            const now = performance.now();
            // Si paso demasiado tiempo desde la ultima tecla, arranca una rafaga nueva.
            if (this._buffer.length && now - this._lastT > this.IDLE_COMMIT_MS) {
                this._buffer = [];
            }
            this._buffer.push({ char: event.key, t: now });
            this._lastT = now;

            // Autocommit cuando el lector deja de enviar teclas (con o sin Enter de cola).
            clearTimeout(this._idleTimer);
            this._idleTimer = setTimeout(() => this._commitBuffer(), this.IDLE_COMMIT_MS);
        }
    }

    _commitBuffer() {
        clearTimeout(this._idleTimer);
        if (this._done) {
            return;
        }
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
        this._done = true; // bloquea doble commit y traga teclas residuales hasta el unmount
        this.state.barcode = buf.map((b) => b.char).join("");
        this.env.services["mail.sound_effects"].play("beep");
        this.confirm(); // autoconfirma, igual que la camara
    }

    _flashWarning(msg) {
        this.state.warning = msg;
        clearTimeout(this._warnTimer);
        this._warnTimer = setTimeout(() => (this.state.warning = ""), 2500);
    }

    onBarcodeInput(ev) {
        // Solo aplica en modo permisivo; en scanner-only el input es readonly.
        if (this.scannerOnly) {
            return;
        }
        this.state.barcode = ev.target.value;
    }

    blockEvent(ev) {
        // En modo permisivo se permite pegar/cortar.
        if (!this.scannerOnly) {
            return;
        }
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

        this._done = true; // traga teclas residuales (incluida la cámara) hasta el unmount
        this.props.getPayload({
            barcode: this.state.barcode.trim()
        });
        this.props.close();
    }

    cancel() {
        this._done = true;
        this.props.getPayload(null);
        this.props.close();
    }
}