/** @odoo-module **/
import { Component, onWillStart, useRef, useState, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MESSAGES = {
    busy: "El asistente está ocupado. Probá en unos segundos.",
    cap: "Se alcanzó el tope de gasto mensual.",
};

/**
 * Chat privado con el Agente IA: conversaciones a la izquierda, mensajes a la derecha.
 * Cada turno es una llamada síncrona a prometeo.ai.conversation.send_message.
 */
export class AiChat extends Component {
    static template = "prometeo_ai_agent.Chat";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.messagesRef = useRef("messages");
        this.inputRef = useRef("input");
        this.state = useState({
            conversations: [],
            currentId: null,
            messages: [],
            models: [],
            modelId: null,
            draft: "",
            sending: false,
            showList: false,
        });
        onWillStart(async () => {
            this.state.models = await this.orm.call("prometeo.ai.conversation", "get_available_models", []);
            const def = this.state.models.find((m) => m.is_default) || this.state.models[0];
            this.state.modelId = def ? def.id : null;
            await this.loadConversations();
            if (this.state.conversations.length) {
                await this.openConversation(this.state.conversations[0].id);
            }
        });
        onPatched(() => this.scrollToBottom());
    }

    async loadConversations() {
        this.state.conversations = await this.orm.searchRead(
            "prometeo.ai.conversation", [], ["name", "write_date", "ai_model_id"], { limit: 100 }
        );
    }

    async openConversation(id) {
        this.state.currentId = id;
        this.state.showList = false;
        this.state.messages = await this.orm.call("prometeo.ai.conversation", "get_messages", [[id]]);
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

    onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.send();
        }
    }

    async send() {
        const text = this.state.draft.trim();
        if (!text || this.state.sending) {
            return;
        }
        this.state.sending = true;
        this.state.draft = "";
        this.state.messages.push({ id: `tmp-${Date.now()}`, role: "user", content: text });
        try {
            if (!this.state.currentId) {
                const [id] = await this.orm.create("prometeo.ai.conversation", [{}]);
                this.state.currentId = id;
            }
            const result = await this.orm.call("prometeo.ai.conversation", "send_message", [
                [this.state.currentId],
                text,
                this.state.modelId,
            ]);
            if (result.status === "ok") {
                this.state.messages.push({ id: `tmp-r-${Date.now()}`, role: "assistant", content: result.reply });
                await this.loadConversations();
            } else {
                this.state.messages.pop();
                this.state.draft = text;
                this.notification.add(result.message || MESSAGES[result.status] || "Error", {
                    type: result.status === "busy" ? "warning" : "danger",
                });
            }
        } catch (error) {
            this.state.messages.pop();
            this.state.draft = text;
            throw error;
        } finally {
            this.state.sending = false;
        }
    }

    scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    formatDate(value) {
        return value ? value.slice(0, 16).replace("T", " ") : "";
    }
}

registry.category("actions").add("prometeo_ai_agent.chat", AiChat);
