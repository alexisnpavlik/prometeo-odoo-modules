/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";

export class DeletionReasonPopup extends Component {
    static components = { Dialog };
    static template = "pos_deletion_reason_log.DeletionReasonPopup";
    static props = ["close", "getPayload", "title"];

    setup() {
        this.pos = usePos();
        this.state = useState({
            reasonId: false,
            note: "",
            warning: "",
        });
        onMounted(() => {
            const reasons = this.reasons;
            if (reasons.length) {
                this.state.reasonId = reasons[0].id;
            }
        });

        // Cuando NO se permite cancelar, el popup solo se cierra confirmando un
        // motivo: se ocultan Cancelar y la X, y además bloqueamos el Escape. El
        // hotkey service escucha en window en fase bubble, así que un listener
        // en fase capture lo intercepta antes y evita que cierre el diálogo
        // (bypass del control). Si se permite cancelar, no tocamos nada.
        this._blockEscape = (ev) => {
            if (ev.key === "Escape") {
                ev.stopPropagation();
                ev.preventDefault();
            }
        };
        onMounted(() => {
            if (!this.allowCancel) {
                window.addEventListener("keydown", this._blockEscape, true);
            }
        });
        onWillUnmount(() => window.removeEventListener("keydown", this._blockEscape, true));
    }

    get reasons() {
        return this.pos.data.models["pos.deletion.reason"].getAll();
    }

    get noteRequired() {
        return Boolean(this.pos.config.require_reason_note);
    }

    get allowCancel() {
        // Por defecto NO se permite cancelar (block=true): solo se habilita si el
        // toggle está explícitamente en false. Si el campo no llegara, se asume
        // bloqueado (comportamiento seguro).
        return this.pos.config.block_reason_cancel === false;
    }

    onReasonChange(ev) {
        this.state.reasonId = parseInt(ev.target.value, 10) || false;
    }

    confirm() {
        // Solo se exige elegir un motivo si hay motivos disponibles. Si no hay
        // ninguno (todos borrados/desactivados) y no se permite cancelar, exigir
        // un motivo inexistente dejaría al cajero atrapado; en ese caso se deja
        // confirmar sin motivo.
        if (this.reasons.length && !this.state.reasonId) {
            this.state.warning = _t("Seleccioná un motivo.");
            return;
        }
        if (this.noteRequired && !this.state.note.trim()) {
            this.state.warning = _t("Escribí una nota de justificación.");
            return;
        }
        this.props.getPayload({
            reason_id: this.state.reasonId,
            reason_note: this.state.note.trim(),
        });
        this.props.close();
    }

    cancel() {
        this.props.getPayload(null);
        this.props.close();
    }
}
