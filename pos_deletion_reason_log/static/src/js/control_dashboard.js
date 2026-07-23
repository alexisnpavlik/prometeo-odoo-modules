/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

const TYPE_LABELS = {
    order: "Orden eliminada",
    line: "Línea eliminada",
    qty_reduction: "Reducción cantidad",
    high_discount: "Descuento alto",
    price_reduction: "Reducción precio",
};

const COLORS = {
    order: "#ef4444",
    line: "#f59e0b",
    qty: "#3b82f6",
    discount: "#8b5cf6",
    price: "#ec4899",
    palette: ["#3b82f6", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"],
};

class PosControlDashboard extends Component {
    static template = "pos_deletion_reason_log.ControlDashboard";

    setup() {
        this.state = useState({
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
            activeTab: "general",
            preset: "30days",
            startDate: "",
            endDate: "",
            pos: "all",
            cashier: "all",
            company: "all",
            dtype: "all",
        });
        this.filtersData = useState({ cajas: [], cajeros: [], empresas: [] });
        this.data = useState({
            kpis: {
                total: 0, n_order: 0, n_line: 0, n_qty: 0, n_discount: 0, n_price: 0,
                amount: 0, units: 0, avg_discount: 0, deletion_rate: 0,
            },
            cashiers: [],
            reasons: [],
            trend: [],
            detail: [],
        });

        this.cashiersRef = useRef("cashiersChart");
        this.reasonsRef = useRef("reasonsChart");
        this.trendRef = useRef("trendChart");
        this._charts = {};

        onWillStart(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
            this.setPresetDates(this.state.preset);
            await this.loadFilters();
            await this.fetchMetrics();
        });
        onMounted(() => this.renderCharts());
        onWillUnmount(() => this.destroyCharts());
    }

    // ---- Fechas / presets ----
    setPresetDates(preset) {
        const fmt = (d) => d.toISOString().slice(0, 10);
        const today = new Date();
        let start = new Date();
        if (preset === "today") {
            // start = today
        } else if (preset === "yesterday") {
            start.setDate(today.getDate() - 1);
            today.setDate(today.getDate() - 1);
        } else if (preset === "7days") {
            start.setDate(today.getDate() - 6);
        } else if (preset === "30days") {
            start.setDate(today.getDate() - 29);
        } else if (preset === "90days") {
            start.setDate(today.getDate() - 89);
        } else if (preset === "all") {
            start = new Date(2020, 0, 1);
        }
        this.state.startDate = fmt(start);
        this.state.endDate = fmt(today);
    }

    onPreset(preset) {
        this.state.preset = preset;
        this.setPresetDates(preset);
        this.applyFilters();
    }
    onStartDate(ev) { this.state.preset = "custom"; this.state.startDate = ev.target.value; }
    onEndDate(ev) { this.state.preset = "custom"; this.state.endDate = ev.target.value; }

    // ---- Datos ----
    async loadFilters() {
        try {
            const res = await rpc("/pos_control_metrics/filters", {});
            Object.assign(this.filtersData, res);
        } catch (e) {
            console.error("filters error", e);
        }
    }

    async fetchMetrics() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const res = await rpc("/pos_control_metrics/metrics", {
                start_date: this.state.startDate || null,
                end_date: this.state.endDate || null,
                pos: this.state.pos,
                cashier: this.state.cashier,
                company: this.state.company,
                dtype: this.state.dtype,
            });
            Object.assign(this.data, res);
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
            this.renderCharts();
        } catch (e) {
            console.error("metrics error", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    switchTab(tab) {
        this.state.activeTab = tab;
        if (tab === "general") {
            // El canvas queda oculto (display:none) mientras esa pestaña no está
            // activa; Chart.js necesita un resize una vez que vuelve a ser visible.
            requestAnimationFrame(() => this.renderCharts());
        }
    }

    applyFilters() { this.fetchMetrics(); }
    clearFilters() {
        this.state.preset = "30days";
        this.setPresetDates("30days");
        this.state.pos = "all";
        this.state.cashier = "all";
        this.state.company = "all";
        this.state.dtype = "all";
        this.fetchMetrics();
    }
    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        this.renderCharts();
    }

    typeLabel(t) { return TYPE_LABELS[t] || t; }
    money(v) {
        return (v || 0).toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // ---- Charts ----
    destroyCharts() {
        Object.values(this._charts).forEach((c) => c && c.destroy());
        this._charts = {};
    }

    renderCharts() {
        if (typeof window.Chart === "undefined") return;
        this.destroyCharts();
        const tick = this.state.theme === "light" ? "#334155" : "#cbd5e1";
        const grid = this.state.theme === "light" ? "rgba(0,0,0,0.08)" : "rgba(255,255,255,0.08)";

        // Ranking de cajeros (barras apiladas por tipo)
        if (this.cashiersRef.el && this.data.cashiers.length) {
            const labels = this.data.cashiers.map((c) => c.cajero);
            this._charts.cashiers = new window.Chart(this.cashiersRef.el, {
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        { label: TYPE_LABELS.order, data: this.data.cashiers.map((c) => c.n_order), backgroundColor: COLORS.order },
                        { label: TYPE_LABELS.line, data: this.data.cashiers.map((c) => c.n_line), backgroundColor: COLORS.line },
                        { label: TYPE_LABELS.qty_reduction, data: this.data.cashiers.map((c) => c.n_qty), backgroundColor: COLORS.qty },
                        { label: TYPE_LABELS.high_discount, data: this.data.cashiers.map((c) => c.n_discount), backgroundColor: COLORS.discount },
                        { label: TYPE_LABELS.price_reduction, data: this.data.cashiers.map((c) => c.n_price), backgroundColor: COLORS.price },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: tick } } },
                    scales: {
                        x: { stacked: true, ticks: { color: tick }, grid: { color: grid } },
                        y: { stacked: true, ticks: { color: tick }, grid: { color: grid }, beginAtZero: true },
                    },
                },
            });
        }

        // Motivos (dona)
        if (this.reasonsRef.el && this.data.reasons.length) {
            this._charts.reasons = new window.Chart(this.reasonsRef.el, {
                type: "doughnut",
                data: {
                    labels: this.data.reasons.map((r) => r.motivo),
                    datasets: [{ data: this.data.reasons.map((r) => r.total), backgroundColor: COLORS.palette }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: "right", labels: { color: tick } } },
                },
            });
        }

        // Tendencia diaria (línea: conteo + importe)
        if (this.trendRef.el && this.data.trend.length) {
            this._charts.trend = new window.Chart(this.trendRef.el, {
                type: "line",
                data: {
                    labels: this.data.trend.map((t) => t.dia),
                    datasets: [
                        { label: "Eventos", data: this.data.trend.map((t) => t.total), borderColor: COLORS.order, backgroundColor: "rgba(239,68,68,0.15)", fill: true, tension: 0.3, yAxisID: "y" },
                        { label: "Importe ($)", data: this.data.trend.map((t) => t.amount), borderColor: COLORS.qty, backgroundColor: "rgba(59,130,246,0.15)", fill: true, tension: 0.3, yAxisID: "y1" },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { labels: { color: tick } } },
                    scales: {
                        x: { ticks: { color: tick }, grid: { color: grid } },
                        y: { position: "left", ticks: { color: tick }, grid: { color: grid }, beginAtZero: true },
                        y1: { position: "right", ticks: { color: tick }, grid: { drawOnChartArea: false }, beginAtZero: true },
                    },
                },
            });
        }
    }
}

registry.category("actions").add("pos_deletion_reason_log.dashboard", PosControlDashboard);
