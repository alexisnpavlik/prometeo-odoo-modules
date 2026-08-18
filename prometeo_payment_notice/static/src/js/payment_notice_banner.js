/** @odoo-module **/

import { Component } from "@odoo/owl";
import { session } from "@web/session";
import { WebClient } from "@web/webclient/webclient";

export class PaymentNoticeBanner extends Component {
    static template = "prometeo_payment_notice.Banner";
    static props = {};

    setup() {
        this.notice = session.prometeo_payment_notice || { mostrar: false, mensaje: "" };
    }
}

WebClient.components = { ...WebClient.components, PaymentNoticeBanner };
