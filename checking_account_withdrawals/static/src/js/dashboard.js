/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class CawDashboard extends Component {
    static template = "checking_account_withdrawals.DashboardTemplate";

    setup() {

        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            company: "all",
            partner: "all",
            search: "",
            page: 1,
            perPage: 15,
            activeTab: "general",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark"
        });

        this.filtersData = useState({
            companies: [],
            partners: [],
            min_date: "",
            max_date: ""
        });

        this.metricsData = useState({
            kpis: {
                total_balance: 0,
                overdue_balance: 0,
                credit_balance: 0,
                total_withdrawn: 0,
                withdrawal_count: 0,
                overdue_installments: 0,
                overdue_rate: 0,
                collected: 0
            },
            charts: {
                balance_trend: { labels: [], companies: {} },
                collected_vs_overdue: { labels: [], collected: [], overdue: [] },
                installment_status: { labels: [], values: [] },
                top_partners: { labels: [], values: [] },
                by_company: { labels: [], values: [] }
            }
        });

        this.withdrawalsData = useState({ records: [], page: 1, pages: 1, total: 0 });
        this.installmentsData = useState({ records: [], page: 1, pages: 1, total: 0 });

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
            Object.values(this.charts).forEach(chart => {
                if (chart) {
                    chart.destroy();
                }
            });
        });
    }

    // --- Manejo de Eventos y Inputs ---
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

    switchTab(tab) {
        this.state.activeTab = tab;
        this.state.page = 1;

        if (tab === "withdrawals") {
            this.loadRecords(tab);
        } else if (tab === "installments") {
            this.loadRecords(tab);
        } else if (tab === "general") {
            // Re-renderizar gráficos en pestaña general para ajustar dimensiones
            setTimeout(() => this.renderAllCharts(), 50);
        }
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        setTimeout(() => this.renderAllCharts(), 50);
    }

    async applyFilters() {
        this.state.page = 1;
        await this.refreshData();
    }

    async clearFilters() {
        this.state.preset = "30days";
        this.setPresetDates("30days");
        this.state.company = "all";
        this.state.partner = "all";
        this.state.search = "";
        this.state.page = 1;
        await this.refreshData();
    }

    // --- Formateadores Auxiliares ---
    formatCurrency(val) {
        return new Intl.NumberFormat('es-AR', {
            style: 'currency',
            currency: 'ARS',
            minimumFractionDigits: 2
        }).format(val || 0);
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
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            return `${year}-${month}-${day}`;
        };

        this.state.startDate = formatDate(start);
        this.state.endDate = formatDate(end);
    }

    // --- Llamadas RPC a Odoo Controller ---
    getFilterPayload() {
        return {
            start_date: this.state.startDate || null,
            end_date: this.state.endDate || null,
            company: this.state.company,
            partner: this.state.partner
        };
    }

    async loadFiltersMetadata() {
        try {
            const data = await rpc("/checking_account_withdrawals/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const metrics = await rpc("/checking_account_withdrawals/metrics", this.getFilterPayload());
            Object.assign(this.metricsData, metrics);
            if (this.state.activeTab === "general") {
                this.renderAllCharts();
            } else if (this.state.activeTab === "withdrawals") {
                await this.loadRecords("withdrawals");
            } else if (this.state.activeTab === "installments") {
                await this.loadRecords("installments");
            }
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    async loadRecords(model) {
        try {
            const data = await rpc("/checking_account_withdrawals/records", {
                ...this.getFilterPayload(),
                model: model,
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage
            });
            const target = model === "installments" ? this.installmentsData : this.withdrawalsData;
            Object.assign(target, data);
        } catch (e) {
            console.error(`Error al cargar ${model}:`, e);
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page = 1;

        // Debounce de búsqueda a 350ms
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => {
            this.loadRecords(this.state.activeTab);
        }, 350);
    }

    async prevPage() {
        if (this.state.page > 1) {
            this.state.page--;
            await this.loadRecords(this.state.activeTab);
        }
    }

    async nextPage() {
        const target = this.state.activeTab === "installments" ? this.installmentsData : this.withdrawalsData;
        if (this.state.page < target.pages) {
            this.state.page++;
            await this.loadRecords(this.state.activeTab);
        }
    }

    exportCSV() {
        const params = new URLSearchParams({
            model: this.state.activeTab === "installments" ? "installments" : "withdrawals",
            start_date: this.state.startDate || '',
            end_date: this.state.endDate || '',
            company: this.state.company,
            partner: this.state.partner,
            search: this.state.search || ''
        });
        window.open(`/checking_account_withdrawals/export?${params.toString()}`, '_blank');
    }

    renderAllCharts() {
        if (this.state.activeTab !== "general") return;

        const isLight = this.state.theme === "light";
        const textColor = isLight ? "#475569" : "#94a3b8";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";

        Chart.defaults.color = textColor;

        const gridConfig = {
            color: gridColor,
            borderColor: "transparent",
            drawBorder: false
        };

        // 1. Evolución del saldo (line, una serie por compañía)
        const trendData = this.metricsData.charts.balance_trend;
        const companies = trendData.companies || {};
        const companyColors = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.08)" },
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.08)" },
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.08)" },
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.08)" },
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.08)" },
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" }
        ];
        const datasets = Object.keys(companies).map((name, idx) => {
            const color = companyColors[idx % companyColors.length];
            return {
                label: name,
                data: companies[name],
                borderColor: color.border,
                backgroundColor: color.bg,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: color.border,
                pointHoverRadius: 6
            };
        });
        this.createOrUpdateChart("chart-balance-trend", "line", {
            labels: trendData.labels,
            datasets: datasets.length ? datasets : [{ label: "Saldo", data: [], borderColor: "#3b82f6" }]
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: "#94a3b8", usePointStyle: true, pointStyle: "circle", padding: 15 } } },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });

        // 2. Cobrado vs. vencido
        const vs = this.metricsData.charts.collected_vs_overdue;
        this.createOrUpdateChart("chart-collected-vs-overdue", "line", {
            labels: vs.labels,
            datasets: [
                { label: "Cobrado", data: vs.collected, borderColor: "#10b981", backgroundColor: "rgba(16, 185, 129, 0.08)", fill: true, tension: 0.4, borderWidth: 3, pointBackgroundColor: "#10b981", pointHoverRadius: 6 },
                { label: "Vencido", data: vs.overdue, borderColor: "#ef4444", backgroundColor: "rgba(239, 68, 68, 0.08)", fill: true, tension: 0.4, borderWidth: 3, pointBackgroundColor: "#ef4444", pointHoverRadius: 6 }
            ]
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: "#94a3b8", usePointStyle: true, pointStyle: "circle", padding: 15 } } },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });

        // 3. Distribución de cuotas por estado (doughnut)
        this.createOrUpdateChart("chart-installment-status", "doughnut", {
            labels: this.metricsData.charts.installment_status.labels,
            datasets: [{
                data: this.metricsData.charts.installment_status.values,
                backgroundColor: ["rgba(59, 130, 246, 0.75)", "rgba(245, 158, 11, 0.75)", "rgba(16, 185, 129, 0.75)", "rgba(239, 68, 68, 0.75)"],
                borderColor: ["#3b82f6", "#f59e0b", "#10b981", "#ef4444"],
                borderWidth: 1.5
            }]
        }, {
            plugins: { legend: { display: true, position: "bottom", labels: { color: "#94a3b8", usePointStyle: true, pointStyle: "circle", padding: 15 } } }
        });

        // 4. Top deudores (bar horizontal)
        this.createOrUpdateChart("chart-top-partners", "bar", {
            labels: this.metricsData.charts.top_partners.labels.map(l => l.length > 22 ? l.substring(0, 19) + "..." : l),
            datasets: [{
                label: "Saldo",
                data: this.metricsData.charts.top_partners.values,
                backgroundColor: "rgba(139, 92, 246, 0.65)",
                borderColor: "#8b5cf6",
                borderWidth: 1.5,
                borderRadius: 4
            }]
        }, {
            indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: (ctx) => ` ${this.formatCurrency(ctx.raw)}` } }
            },
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
                y: { grid: { display: false } }
            }
        });

        // 5. Retiros por compañía
        this.createOrUpdateChart("chart-by-company", "bar", {
            labels: this.metricsData.charts.by_company.labels,
            datasets: [{
                label: "Retirado",
                data: this.metricsData.charts.by_company.values,
                backgroundColor: "rgba(16, 185, 129, 0.65)",
                borderColor: "#10b981",
                borderWidth: 1.5,
                borderRadius: 6
            }]
        }, {
            scales: {
                x: { grid: { display: false } },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });
    }

    createOrUpdateChart(canvasId, type, data, options = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext("2d");

        // Destruir instancia existente para evitar bugs de hover y parpadeo
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }

        // Estilos base globales para Chart.js
        Chart.defaults.color = "#94a3b8";
        Chart.defaults.font.family = "'Inter', sans-serif";
        Chart.defaults.font.size = 10;

        const mergedOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: type === "doughnut" },
                tooltip: {
                    backgroundColor: "rgba(15, 23, 42, 0.95)",
                    borderColor: "rgba(255, 255, 255, 0.08)",
                    borderWidth: 1,
                    padding: 8,
                    titleColor: "#fff",
                    bodyColor: "#94a3b8"
                }
            }
        };

        if (options.plugins) {
            Object.assign(mergedOptions.plugins, options.plugins);
            delete options.plugins;
        }
        Object.assign(mergedOptions, options);

        this.charts[canvasId] = new Chart(ctx, {
            type: type,
            data: data,
            options: mergedOptions
        });
    }
}

// Registrar en la categoría "actions" del web backend
registry.category("actions").add("checking_account_withdrawals.dashboard", CawDashboard);
