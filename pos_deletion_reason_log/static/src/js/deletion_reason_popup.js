/** @odoo-module **/

import { Component, useState, onMounted, useRef } from "@odoo/owl";
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
        this.noteRef = useRef("noteInput");
        onMounted(() => {
            const reasons = this.reasons;
            if (reasons.length) {
                this.state.reasonId = reasons[0].id;
            }
        });
    }

    get reasons() {
        return this.pos.data.models["pos.deletion.reason"].getAll();
    }

    onReasonChange(ev) {
        this.state.reasonId = parseInt(ev.target.value, 10) || false;
    }

    confirm() {
        if (!this.state.reasonId) {
            this.state.warning = _t("Seleccioná un motivo.");
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
