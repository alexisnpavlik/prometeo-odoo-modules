/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class PosSalesAdvisorDashboard extends Component {
    static template = "pos_sales_advisor.DashboardTemplate";

    setup() {
        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            advisor: "all",
            pos: "all",
            company: "all",
            search: "",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
        });

        this.filtersData = useState({
            advisors: [],
            pos_configs: [],
            companies: [],
            min_date: "",
            max_date: "",
        });

        this.metricsData = useState({
            kpis: {
                net_sales: 0,
                gross_sales: 0,
                refunds: 0,
                orders_count: 0,
                ticket_average: 0,
                without_advisor_count: 0,
                without_advisor_pct: 0,
            },
            charts: {
                advisor_ranking: { labels: [], values: [] },
                sales_trend: { labels: [], advisors: {}, timeframe: "Diario" },
                advisor_share: { labels: [], values: [] },
            },
            table: [],
        });

        this.charts = {};

        onWillStart(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
            this.setPresetDates(this.state.preset);
            await this.loadFiltersMetadata();
            await this.refreshData();
        });

        onMounted(() => {
            this.renderAllCharts();
        });

        onWillUnmount(() => {
            Object.values(this.charts).forEach((chart) => {
                if (chart) {
                    chart.destroy();
                }
            });
        });
    }

    // --- Getters reactivos ---
    get filteredTableRows() {
        const search = (this.state.search || "").toLowerCase().trim();
        if (!search) return this.metricsData.table;
        return this.metricsData.table.filter(
            (r) => r.asesor && r.asesor.toLowerCase().includes(search)
        );
    }

    // --- Manejo de eventos ---
    onPresetClick(preset) {
        this.state.preset = preset;
        this.setPresetDates(preset);
    }

    onStartDateChange(ev) {
        this.state.preset = "custom";
        this.state.startDate = ev.target.value;
    }

    onEndDateChange(ev) {
        this.state.preset = "custom";
        this.state.endDate = ev.target.value;
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        setTimeout(() => this.renderAllCharts(), 50);
    }

    async applyFilters() {
        await this.refreshData();
    }

    async clearFilters() {
        this.state.preset = "30days";
        this.setPresetDates("30days");
        this.state.advisor = "all";
        this.state.pos = "all";
        this.state.company = "all";
        this.state.search = "";
        await this.refreshData();
    }

    // --- Formateadores ---
    formatCurrency(val) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency",
            currency: "ARS",
            minimumFractionDigits: 2,
        }).format(val || 0);
    }

    formatPercent(val) {
        return `${(val || 0).toFixed(1)}%`;
    }

    // --- Fechas predefinidas ---
    setPresetDates(preset) {
        const today = new Date();
        let start = new Date();
        let end = new Date();

        switch (preset) {
            case "today":
                break;
            case "yesterday":
                start.setDate(today.getDate() - 1);
                end.setDate(today.getDate() - 1);
                break;
            case "7days":
                start.setDate(today.getDate() - 7);
                break;
            case "30days":
                start.setDate(today.getDate() - 30);
                break;
            case "60days":
                start.setDate(today.getDate() - 60);
                break;
            case "90days":
                start.setDate(today.getDate() - 90);
                break;
            case "all":
                start = null;
                end = null;
                break;
        }

        const formatDate = (d) => {
            if (!d) return "";
            const year = d.getFullYear();
            const month = String(d.getMonth() + 1).padStart(2, "0");
            const day = String(d.getDate()).padStart(2, "0");
            return `${year}-${month}-${day}`;
        };

        this.state.startDate = formatDate(start);
        this.state.endDate = formatDate(end);
    }

    // --- RPC ---
    async loadFiltersMetadata() {
        try {
            const data = await rpc("/pos_sales_advisor/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const metrics = await rpc("/pos_sales_advisor/metrics", {
                start_date: this.state.startDate || null,
                end_date: this.state.endDate || null,
                advisor: this.state.advisor,
                pos: this.state.pos,
                company: this.state.company,
            });
            Object.assign(this.metricsData, metrics);
            setTimeout(() => this.renderAllCharts(), 50);
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas de asesores:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    exportCSV() {
        const params = new URLSearchParams({
            start_date: this.state.startDate || "",
            end_date: this.state.endDate || "",
            advisor: this.state.advisor,
            pos: this.state.pos,
            company: this.state.company,
        });
        window.open(`/pos_sales_advisor/export?${params.toString()}`, "_blank");
    }

    // --- Gráficos ---
    createOrUpdateChart(canvasId, type, data, extraOptions = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        this.charts[canvasId] = new Chart(canvas, {
            type: type,
            data: data,
            options: Object.assign(
                {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                },
                extraOptions
            ),
        });
    }

    renderAllCharts() {
        const isLight = this.state.theme === "light";
        const textColor = isLight ? "#475569" : "#94a3b8";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";
        Chart.defaults.color = textColor;

        const gridConfig = {
            color: gridColor,
            borderColor: "transparent",
            drawBorder: false,
        };

        const palette = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.08)" },
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.08)" },
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.08)" },
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.08)" },
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.08)" },
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" },
        ];

        // 1. Ranking de asesores (barras horizontales por neto)
        const ranking = this.metricsData.charts.advisor_ranking;
        this.createOrUpdateChart("chart-advisor-ranking", "bar", {
            labels: ranking.labels,
            datasets: [{
                label: "Ventas Netas",
                data: ranking.values,
                backgroundColor: "rgba(59, 130, 246, 0.5)",
                borderColor: "#3b82f6",
                borderWidth: 2,
                borderRadius: 6,
            }],
        }, {
            indexAxis: "y",
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
                y: { grid: gridConfig },
            },
        });

        // 2. Evolución temporal por asesor (líneas, top 6)
        const trend = this.metricsData.charts.sales_trend;
        const datasets = [];
        let colorIdx = 0;
        Object.keys(trend.advisors).forEach((advisorName) => {
            const color = palette[colorIdx % palette.length];
            colorIdx++;
            datasets.push({
                label: advisorName,
                data: trend.advisors[advisorName],
                borderColor: color.border,
                backgroundColor: color.bg,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: color.border,
                pointHoverRadius: 6,
            });
        });
        this.createOrUpdateChart("chart-advisor-trend", "line", {
            labels: trend.labels,
            datasets: datasets,
        }, {
            plugins: {
                legend: {
                    display: true,
                    position: "top",
                    labels: {
                        color: textColor,
                        boxWidth: 12,
                        boxHeight: 12,
                        usePointStyle: true,
                        pointStyle: "circle",
                        font: { size: 11, weight: "bold" },
                        padding: 15,
                    },
                },
            },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
            },
        });

        // 3. Participación por asesor (doughnut)
        const share = this.metricsData.charts.advisor_share;
        this.createOrUpdateChart("chart-advisor-share", "doughnut", {
            labels: share.labels,
            datasets: [{
                data: share.values,
                backgroundColor: palette.map((c) => c.border),
                borderWidth: 0,
            }],
        }, {
            cutout: "62%",
            plugins: {
                legend: {
                    display: true,
                    position: "bottom",
                    labels: {
                        color: textColor,
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                        pointStyle: "circle",
                        font: { size: 11 },
                        padding: 10,
                    },
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const total = share.values.reduce((a, b) => a + b, 0);
                            const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                            return ` ${ctx.label}: ${pct}% (${this.formatCurrency(ctx.parsed)})`;
                        },
                    },
                },
            },
        });
    }
}

registry.category("actions").add("pos_sales_advisor.dashboard", PosSalesAdvisorDashboard);
