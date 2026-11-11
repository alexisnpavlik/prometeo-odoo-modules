/** @odoo-module **/
import { Component, markup, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { escape } from "@web/core/utils/strings";

const STEP_EVENT = "prometeo_ai_agent/step";
const MESSAGES = {
    busy: "El asistente está ocupado. Probá en unos segundos.",
    cap: "Se alcanzó el tope de gasto mensual.",
};
const SUGGESTIONS = [
    "¿Qué traslados quedaron trabados esta semana?",
    "¿Qué productos están sin stock?",
    "¿Cuánto vendió cada caja ayer?",
    "¿Qué facturas de proveedor están vencidas?",
];

/** Texto del agente → HTML seguro: **negrita**, listas con "- " y párrafos. */
export function formatReply(text) {
    const lines = escape(text || "").split("\n");
    let html = "";
    let inList = false;
    for (const raw of lines) {
        const line = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        const item = line.match(/^\s*[-•*]\s+(.*)$/);
        if (item) {
            html += (inList ? "" : "<ul>") + `<li>${item[1]}</li>`;
            inList = true;
            continue;
        }
        if (inList) {
            html += "</ul>";
            inList = false;
        }
        if (line.trim()) {
            html += `<p>${line}</p>`;
        }
    }
    return markup(html + (inList ? "</ul>" : ""));
}

function dayGroup(value) {
    if (!value) {
        return "Anteriores";
    }
    const date = new Date(value.replace(" ", "T") + "Z");
    const today = new Date();
    const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const diffDays = Math.floor((startToday - new Date(date.getFullYear(), date.getMonth(), date.getDate())) / 86400000);
    if (diffDays <= 0) {
        return "Hoy";
    }
    if (diffDays === 1) {
        return "Ayer";
    }
    if (diffDays < 7) {
        return "Esta semana";
    }
    return "Anteriores";
}

/**
 * Chat privado con el Agente IA. Cada turno es una llamada síncrona; mientras corre,
 * el servidor manda por el bus cada consulta que hace el agente y se muestra en vivo.
 */
export class AiChat extends Component {
    static template = "prometeo_ai_agent.Chat";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        this.action = useService("action");
        this.messagesRef = useRef("messages");
        this.inputRef = useRef("input");
        this.suggestions = SUGGESTIONS;
        this.state = useState({
            conversations: [],
            currentId: null,
            messages: [],
            models: [],
            modelId: null,
            draft: "",
            sending: false,
            steps: [],
            elapsed: 0,
            showList: false,
            alerts: [],
            showAlerts: false,
        });
        this.onStep = (payload) => {
            if (this.state.sending && payload.conversation_id === this.state.currentId) {
                this.state.steps.push(payload.text);
            }
        };
        this.busService.subscribe(STEP_EVENT, this.onStep);
        onWillUnmount(() => {
            this.busService.unsubscribe(STEP_EVENT, this.onStep);
            clearInterval(this.timer);
        });
        onWillStart(async () => {
            this.state.models = await this.orm.call("prometeo.ai.conversation", "get_available_models", []);
            const def = this.state.models.find((m) => m.is_default) || this.state.models[0];
            this.state.modelId = def ? def.id : null;
            await this.loadConversations();
            await this.loadAlerts();
            if (this.state.conversations.length) {
                await this.openConversation(this.state.conversations[0].id);
            }
        });
        onPatched(() => this.scrollToBottom());
    }

    get groupedConversations() {
        const groups = [];
        for (const conv of this.state.conversations) {
            const label = dayGroup(conv.write_date);
            let group = groups.find((g) => g.label === label);
            if (!group) {
                group = { label, items: [] };
                groups.push(group);
            }
            group.items.push(conv);
        }
        return groups;
    }

    async loadAlerts() {
        const alerts = await this.orm.searchRead(
            "prometeo.ai.alert",
            [["state", "=", "new"]],
            ["name", "summary", "severity", "res_model", "last_seen", "routine_id"],
            { limit: 50, order: "severity_sequence, last_seen desc" }
        );
        this.state.alerts = alerts;
    }

    async alertAction(alert, method) {
        const result = await this.orm.call("prometeo.ai.alert", method, [[alert.id]]);
        if (result && result.type) {
            await this.action.doAction(result);
            return;
        }
        await this.loadAlerts();
    }

    askAbout(alert) {
        this.state.showAlerts = false;
        this.newConversation();
        this.state.draft = `Explicame esta alerta y qué conviene hacer: "${alert.name}"`;
        this.orm.call("prometeo.ai.alert", "action_mark_seen", [[alert.id]]);
    }

    openAllAlerts() {
        this.action.doAction("prometeo_ai_agent.action_alert_inbox");
    }

    async loadConversations() {
        this.state.conversations = await this.orm.searchRead(
            "prometeo.ai.conversation", [], ["name", "write_date", "ai_model_id"], { limit: 100 }
        );
    }

    async openConversation(id) {
        this.state.currentId = id;
        this.state.showList = false;
        const messages = await this.orm.call("prometeo.ai.conversation", "get_messages", [[id]]);
        this.state.messages = messages.map((m) => ({ ...m, html: formatReply(m.content), steps: [] }));
        const conv = this.state.conversations.find((c) => c.id === id);
        if (conv && conv.ai_model_id) {
            this.state.modelId = conv.ai_model_id[0];
        }
    }

    newConversation() {
        this.state.currentId = null;
        this.state.messages = [];
        this.state.showList = false;
        this.inputRef.el?.focus();
    }

    async deleteConversation(id, ev) {
        ev.stopPropagation();
        await this.orm.unlink("prometeo.ai.conversation", [id]);
        if (this.state.currentId === id) {
            this.newConversation();
        }
        await this.loadConversations();
    }

    useSuggestion(text) {
        this.state.draft = text;
        this.send();
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    startTimer() {
        this.state.elapsed = 0;
        this.state.steps = [];
        const started = Date.now();
        this.timer = setInterval(() => {
            this.state.elapsed = Math.round((Date.now() - started) / 1000);
        }, 1000);
    }

    async send() {
        const text = this.state.draft.trim();
        if (!text || this.state.sending) {
            return;
        }
        this.state.draft = "";
        this.state.messages.push({ id: `tmp-${Date.now()}`, role: "user", content: text });
        let created = false;
        try {
            if (!this.state.currentId) {
                const [id] = await this.orm.create("prometeo.ai.conversation", [{}]);
                this.state.currentId = id;
                created = true;
            }
            this.state.sending = true;
            this.startTimer();
            const result = await this.orm.call("prometeo.ai.conversation", "send_message", [
                [this.state.currentId],
                text,
                this.state.modelId,
            ]);
            if (result.status === "ok") {
                this.state.messages.push({
                    id: `tmp-r-${Date.now()}`,
                    role: "assistant",
                    content: result.reply,
                    html: formatReply(result.reply),
                    steps: [...this.state.steps],
                    seconds: this.state.elapsed,
                });
                await this.loadConversations();
            } else {
                this.restoreDraft(text);
                if (created) {
                    await this.orm.unlink("prometeo.ai.conversation", [this.state.currentId]);
                    this.state.currentId = null;
                }
                this.notification.add(result.message || MESSAGES[result.status] || "Error", {
                    type: result.status === "busy" ? "warning" : "danger",
                });
            }
        } catch (error) {
            this.restoreDraft(text);
            throw error;
        } finally {
            clearInterval(this.timer);
            this.state.sending = false;
        }
    }

    restoreDraft(text) {
        this.state.messages.pop();
        this.state.draft = text;
    }

    toggleSteps(msg) {
        msg.showSteps = !msg.showSteps;
    }

    scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }
}

registry.category("actions").add("prometeo_ai_agent.chat", AiChat);
