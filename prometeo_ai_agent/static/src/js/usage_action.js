/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre"];

/** Consumo del Agente IA por mes: gasto contra tope y tablas por rutina y por modelo. */
export class AiUsage extends Component {
    static template = "prometeo_ai_agent.Usage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const now = new Date();
        this.state = useState({ year: now.getFullYear(), month: now.getMonth() + 1, data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("prometeo.ai.run", "get_usage_summary", [this.state.year, this.state.month]);
    }

    async shift(delta) {
        let month = this.state.month + delta;
        let year = this.state.year;
        if (month < 1) { month = 12; year -= 1; }
        if (month > 12) { month = 1; year += 1; }
        this.state.month = month;
        this.state.year = year;
        await this.load();
    }

    get monthLabel() {
        return `${MONTHS[this.state.month - 1]} ${this.state.year}`;
    }

    money(value) {
        return `USD ${(value || 0).toFixed(2)}`;
    }

    number(value) {
        return (value || 0).toLocaleString("es-AR");
    }

    openDetail() {
        const end = this.state.month === 12 ? `${this.state.year + 1}-01-01` : `${this.state.year}-${String(this.state.month + 1).padStart(2, "0")}-01`;
        const start = `${this.state.year}-${String(this.state.month).padStart(2, "0")}-01`;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Corridas de ${this.monthLabel}`,
            res_model: "prometeo.ai.run",
            views: [[false, "list"], [false, "pivot"]],
            domain: [["create_date", ">=", start], ["create_date", "<", end]],
        });
    }
}

registry.category("actions").add("prometeo_ai_agent.usage", AiUsage);
