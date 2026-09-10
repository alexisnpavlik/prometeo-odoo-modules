/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onWillUnmount, useEffect, useState, useRef } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadBundle } from "@web/core/assets";

const DETAIL_PAGE_SIZE = 50;

const TYPE_LABELS = {
    order: "Orden eliminada",
    line: "Línea eliminada",
    qty_reduction: "Reducción cantidad",
    high_discount: "Descuento alto",
    price_reduction: "Reducción precio",
    price_increase: "Aumento precio",
    refund: "Reembolso",
};

const COLORS = {
    order: "#ef4444",
    line: "#f59e0b",
    qty: "#3b82f6",
    discount: "#8b5cf6",
    price: "#ec4899",
    price_up: "#14b8a6",
    refund: "#f97316",
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
            productsModal: { open: false, subtitle: "", items: [] },
            showFilters: false,
            page: 0,
        });
        this.filtersData = useState({ cajas: [], cajeros: [], empresas: [] });
        this.data = useState({
            kpis: {
                total: 0, n_order: 0, n_line: 0, n_qty: 0, n_discount: 0, n_price: 0, n_price_up: 0,
                amount: 0, units: 0, avg_discount: 0, deletion_rate: 0,
                n_refund: 0, refund_amount: 0, refund_units: 0,
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
            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                // Sin gráficos, pero el resto del dashboard tiene que abrir igual
                console.warn("Chart.js no disponible; el dashboard sigue sin gráficos", e);
            }
            this.setPresetDates(this.state.preset);
            await this.loadFilters();
            await this.fetchMetrics();
        });
        // Los gráficos se dibujan DESPUÉS de que OWL parchea el DOM. Con el
        // requestAnimationFrame que hacía switchTab, el callback corría antes
        // del patch: el pane general seguía en display:none, Chart.js medía
        // 0x0 y el canvas quedaba muerto (ningún resize posterior lo
        // recupera). Se notaba sobre todo en Evolución Temporal, el último
        // gráfico de la grilla. useEffect corre dentro del patch, con la
        // pestaña ya visible.
        useEffect(
            (tab) => {
                if (tab === "general") {
                    this.renderCharts();
                }
            },
            () => [this.state.activeTab]
        );
        onWillUnmount(() => this.destroyCharts());
    }

    // ---- Fechas / presets ----
    setPresetDates(preset) {
        const fmt = (d) =>
            `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
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
        } else if (preset === "60days") {
            start.setDate(today.getDate() - 59);
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
            this.state.page = 0;
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
            this.renderCharts();
        } catch (e) {
            console.error("metrics error", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    // ---- Paginación del detalle ----
    get totalPages() {
        return Math.max(1, Math.ceil(this.data.detail.length / DETAIL_PAGE_SIZE));
    }
    get detailPage() {
        const from = this.state.page * DETAIL_PAGE_SIZE;
        return this.data.detail.slice(from, from + DETAIL_PAGE_SIZE);
    }
    prevPage() {
        if (this.state.page > 0) this.state.page--;
    }
    nextPage() {
        if (this.state.page < this.totalPages - 1) this.state.page++;
    }

    // ---- Exportación ----
    exportDetailExcel() {
        // Exporta el detalle con los filtros activos. Va por GET a un endpoint
        // http (no rpc) para que el navegador maneje la descarga del archivo.
        const params = new URLSearchParams({
            start_date: this.state.startDate || "",
            end_date: this.state.endDate || "",
            pos: this.state.pos,
            cashier: this.state.cashier,
            company: this.state.company,
            dtype: this.state.dtype,
        });
        window.open(`/pos_control_metrics/export_detail?${params.toString()}`, "_blank");
    }

    switchTab(tab) {
        // El redibujo de los gráficos lo dispara el useEffect de setup().
        this.state.activeTab = tab;
    }

    toggleFilters() {
        // Panel de filtros plegable: solo visible en pantallas chicas
        this.state.showFilters = !this.state.showFilters;
    }
    applyFilters() {
        this.state.showFilters = false;
        this.fetchMetrics();
    }
    clearFilters() {
        this.state.preset = "30days";
        this.setPresetDates("30days");
        this.state.pos = "all";
        this.state.cashier = "all";
        this.state.company = "all";
        this.state.dtype = "all";
        this.state.showFilters = false;
        this.fetchMetrics();
    }
    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        this.renderCharts();
    }

    openProducts(d) {
        this.state.productsModal = {
            open: true,
            subtitle: [d.fecha, d.cajero, d.caja].filter(Boolean).join(" · "),
            items: d.productos || [],
        };
    }
    closeProducts() {
        this.state.productsModal = { open: false, subtitle: "", items: [] };
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
        const tick = this.state.theme === "light" ? "#475569" : "#94a3b8";
        const grid = this.state.theme === "light" ? "rgba(0,0,0,0.05)" : "rgba(255,255,255,0.04)";
        // En teléfono la leyenda de 7 series se come todo el alto del panel
        const isPhone = window.innerWidth <= 768;
        const legendLabels = { color: tick, boxWidth: 12, boxHeight: 12, padding: 8, font: { size: 11 } };

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
                        { label: TYPE_LABELS.price_increase, data: this.data.cashiers.map((c) => c.n_price_up), backgroundColor: COLORS.price_up },
                        { label: TYPE_LABELS.refund, data: this.data.cashiers.map((c) => c.n_refund), backgroundColor: COLORS.refund },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: !isPhone, labels: legendLabels } },
                    scales: {
                        x: { stacked: true, ticks: { color: tick, maxRotation: isPhone ? 0 : 50, autoSkip: true }, grid: { color: grid } },
                        y: { stacked: true, ticks: { color: tick, maxTicksLimit: isPhone ? 5 : 11 }, grid: { color: grid }, beginAtZero: true },
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
                    plugins: { legend: { position: isPhone ? "bottom" : "right", labels: legendLabels } },
                },
            });
        }

        // Evolución temporal (línea: conteo + importe)
        if (this.trendRef.el && this.data.trend.length) {
            this._charts.trend = new window.Chart(this.trendRef.el, {
                type: "line",
                data: {
                    labels: this.data.trend.map((t) => t.dia.slice(5).replace("-", "/")),
                    datasets: [
                        { label: "Eventos", data: this.data.trend.map((t) => t.total), borderColor: COLORS.order, backgroundColor: "rgba(239,68,68,0.15)", fill: true, tension: 0.3, yAxisID: "y" },
                        { label: "Reembolsos", data: this.data.trend.map((t) => t.n_refund), borderColor: COLORS.refund, backgroundColor: "rgba(249,115,22,0.15)", fill: true, tension: 0.3, yAxisID: "y" },
                        { label: "Importe ($)", data: this.data.trend.map((t) => t.amount), borderColor: COLORS.qty, backgroundColor: "rgba(59,130,246,0.15)", fill: true, tension: 0.3, yAxisID: "y1" },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: legendLabels },
                        tooltip: { callbacks: { title: (items) => this.data.trend[items[0].dataIndex].dia } },
                    },
                    scales: {
                        x: { ticks: { color: tick, maxRotation: 0, autoSkip: true, autoSkipPadding: 8 }, grid: { color: grid } },
                        y: { position: "left", ticks: { color: tick, maxTicksLimit: 6 }, grid: { color: grid }, beginAtZero: true },
                        y1: {
                            position: "right", beginAtZero: true, grid: { drawOnChartArea: false },
                            ticks: {
                                color: tick, maxTicksLimit: 5,
                                callback: (v) => Math.abs(v) >= 1000
                                    ? `${(v / 1000).toLocaleString("es-AR", { maximumFractionDigits: 1 })}k`
                                    : v,
                            },
                        },
                    },
                },
            });
        }

        // El canvas puede medirse antes de que el layout flex termine de
        // asentar (más notorio en la dona, que queda descentrada/recortada
        // por el overflow:hidden del panel). Forzar un resize post-layout.
        requestAnimationFrame(() => {
            Object.values(this._charts).forEach((c) => c && c.resize());
        });
    }
}

registry.category("actions").add("pos_deletion_reason_log.dashboard", PosControlDashboard);
