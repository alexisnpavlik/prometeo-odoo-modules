/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class AccountDashboardMetrics extends Component {
    static template = "account_management_metrics.DashboardTemplate";

    setup() {

        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            company: "all",
            docType: "all",
            search: "",
            page: 1,
            draftPage: 1,
            perPage: 15,
            activeTab: "general",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark"
        });

        this.filtersData = useState({
            companies: [],
            doc_types: [],
            min_date: "",
            max_date: ""
        });

        this.metricsData = useState({
            kpis: {
                total_facturado: 0,
                total_facturado_neto: 0,
                comprobantes_emitidos: 0,
                facturas_emitidas: 0,
                promedio_por_factura: 0,
                nc_emitidas: 0,
                monto_nc: 0,
                borradores: 0,
                monto_borradores: 0,
                canceladas: 0,
                monto_canceladas: 0,
                tasa_cancelacion: 0
            },
            charts: {
                invoicing_trend: { labels: [], companies: {}, timeframe: "Diario" },
                by_company: { labels: [], values: [] },
                doc_types: { labels: [], counts: [], amounts: [] },
                status: { labels: [], values: [] },
                payment_methods: { labels: [], values: [] }
            }
        });

        this.invoicesData = useState({
            invoices: [],
            page: 1,
            pages: 1,
            total: 0
        });

        this.draftsData = useState({
            invoices: [],
            page: 1,
            pages: 1,
            total: 0
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
        this.state.draftPage = 1;

        if (tab === "invoices") {
            this.loadInvoices();
        } else if (tab === "drafts") {
            this.loadDrafts();
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
        this.state.docType = "all";
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
            doc_type: this.state.docType
        };
    }

    async loadFiltersMetadata() {
        try {
            const data = await rpc("/account_management_metrics/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData(force = false) {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";

        try {
            const metrics = await rpc("/account_management_metrics/metrics", this.getFilterPayload());
            Object.assign(this.metricsData, metrics);

            if (this.state.activeTab === "general") {
                this.renderAllCharts();
            } else if (this.state.activeTab === "invoices") {
                await this.loadInvoices();
            } else if (this.state.activeTab === "drafts") {
                await this.loadDrafts();
            }

            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    async loadInvoices() {
        try {
            const data = await rpc("/account_management_metrics/raw_invoices", {
                ...this.getFilterPayload(),
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage
            });
            Object.assign(this.invoicesData, data);
        } catch (e) {
            console.error("Error al cargar comprobantes:", e);
        }
    }

    async loadDrafts() {
        try {
            const data = await rpc("/account_management_metrics/raw_invoices", {
                ...this.getFilterPayload(),
                state: "draft",
                page: this.state.draftPage,
                per_page: this.state.perPage
            });
            Object.assign(this.draftsData, data);
        } catch (e) {
            console.error("Error al cargar facturas en borrador:", e);
        }
    }

    async prevDraftPage() {
        if (this.state.draftPage > 1) {
            this.state.draftPage--;
            await this.loadDrafts();
        }
    }

    async nextDraftPage() {
        if (this.state.draftPage < this.draftsData.pages) {
            this.state.draftPage++;
            await this.loadDrafts();
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page = 1;

        // Debounce de búsqueda a 350ms
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => {
            this.loadInvoices();
        }, 350);
    }

    async prevPage() {
        if (this.state.page > 1) {
            this.state.page--;
            await this.loadInvoices();
        }
    }

    async nextPage() {
        if (this.state.page < this.invoicesData.pages) {
            this.state.page++;
            await this.loadInvoices();
        }
    }

    exportCSV() {
        // Redireccionar al endpoint de tipo HTTP de exportación pasándole filtros GET
        const params = new URLSearchParams({
            start_date: this.state.startDate || '',
            end_date: this.state.endDate || '',
            company: this.state.company,
            doc_type: this.state.docType,
            search: this.state.search || ''
        });
        window.open(`/account_management_metrics/export?${params.toString()}`, '_blank');
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

        // 1. Tendencia de Facturación (Line) - Una línea por empresa
        const trendData = this.metricsData.charts.invoicing_trend;
        const companies = trendData.companies || {};
        const datasets = [];

        const companyColors = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.08)" },   // Neon Blue
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.08)" },  // Purple
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.08)" },  // Green/Emerald
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.08)" },  // Amber/Orange
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.08)" },  // Pink
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" }    // Cyan
        ];

        let colorIdx = 0;
        Object.keys(companies).forEach(companyName => {
            const color = companyColors[colorIdx % companyColors.length];
            colorIdx++;
            datasets.push({
                label: companyName,
                data: companies[companyName],
                borderColor: color.border,
                backgroundColor: color.bg,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: color.border,
                pointHoverRadius: 6
            });
        });

        // Fallback si no hay empresas o datos
        if (datasets.length === 0) {
            datasets.push({
                label: "Facturación",
                data: [],
                borderColor: "#3b82f6",
                backgroundColor: "rgba(59, 130, 246, 0.08)",
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: "#3b82f6",
                pointHoverRadius: 6
            });
        }

        this.createOrUpdateChart("chart-invoicing-trend", "line", {
            labels: trendData.labels,
            datasets: datasets
        }, {
            plugins: {
                legend: {
                    display: true,
                    position: "top",
                    labels: {
                        color: "#94a3b8",
                        boxWidth: 12,
                        boxHeight: 12,
                        usePointStyle: true,
                        pointStyle: "circle",
                        font: { size: 11, weight: "bold" },
                        padding: 15
                    }
                }
            },
            scales: {
                x: { grid: gridConfig },
                y: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } }
            }
        });

        // 2. Cobros por Medio de Pago (Horizontal Bar - Porcentual)
        const payValues = this.metricsData.charts.payment_methods.values;
        const totalPayment = payValues.reduce((a, b) => a + b, 0);
        const paymentLabels = this.metricsData.charts.payment_methods.labels.map((l) => {
            return l.length > 18 ? l.substring(0, 15) + "..." : l;
        });
        const pctValues = payValues.map(val => totalPayment > 0 ? parseFloat(((val / totalPayment) * 100).toFixed(1)) : 0);

        this.createOrUpdateChart("chart-payment-methods", "bar", {
            labels: paymentLabels,
            datasets: [{
                label: "Participación",
                data: pctValues,
                backgroundColor: [
                    "rgba(16, 185, 129, 0.65)",
                    "rgba(59, 130, 246, 0.65)",
                    "rgba(139, 92, 246, 0.65)",
                    "rgba(245, 158, 11, 0.65)",
                    "rgba(239, 68, 68, 0.65)",
                    "rgba(6, 182, 212, 0.65)",
                    "rgba(236, 72, 153, 0.65)",
                    "rgba(107, 114, 128, 0.65)",
                    "rgba(168, 85, 247, 0.65)"
                ],
                borderColor: [
                    "#10b981",
                    "#3b82f6",
                    "#8b5cf6",
                    "#f59e0b",
                    "#ef4444",
                    "#06b6d4",
                    "#ec4899",
                    "#6b7280",
                    "#a855f7"
                ],
                borderWidth: 1.5,
                borderRadius: 4
            }]
        }, {
            indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const pct = context.raw;
                            const val = payValues[context.dataIndex];
                            const fullLabel = this.metricsData.charts.payment_methods.labels[context.dataIndex];
                            return ` ${fullLabel}: ${pct}% (${this.formatCurrency(val)})`;
                        }
                    }
                }
            },
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => `${v}%` } },
                y: { grid: { display: false } }
            }
        });

        // 4. Comprobantes por Tipo (cantidad, tooltip con monto)
        const docAmounts = this.metricsData.charts.doc_types.amounts;
        const docLabelsFull = this.metricsData.charts.doc_types.labels;
        this.createOrUpdateChart("chart-doc-types", "bar", {
            labels: docLabelsFull.map(l => l.length > 25 ? l.substring(0, 22) + "..." : l),
            datasets: [{
                label: "Comprobantes",
                data: this.metricsData.charts.doc_types.counts,
                backgroundColor: "rgba(139, 92, 246, 0.65)",
                borderColor: "#8b5cf6",
                borderWidth: 1.5,
                borderRadius: 4
            }]
        }, {
            indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const amount = docAmounts[context.dataIndex] || 0;
                            return ` ${docLabelsFull[context.dataIndex]}: ${context.raw} comprobantes (${this.formatCurrency(amount)})`;
                        }
                    }
                }
            },
            scales: {
                x: { grid: gridConfig, ticks: { precision: 0 } },
                y: { grid: { display: false } }
            }
        });

        // 5. Facturación por Empresa
        this.createOrUpdateChart("chart-by-company", "bar", {
            labels: this.metricsData.charts.by_company.labels,
            datasets: [{
                label: "Facturación",
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

        // 6. Distribución por Estado (Doughnut)
        this.createOrUpdateChart("chart-status", "doughnut", {
            labels: this.metricsData.charts.status.labels,
            datasets: [{
                data: this.metricsData.charts.status.values,
                backgroundColor: [
                    "rgba(16, 185, 129, 0.75)",
                    "rgba(245, 158, 11, 0.75)",
                    "rgba(239, 68, 68, 0.75)"
                ],
                borderColor: [
                    "#10b981",
                    "#f59e0b",
                    "#ef4444"
                ],
                borderWidth: 1.5
            }]
        }, {
            plugins: {
                legend: {
                    display: true,
                    position: "bottom",
                    labels: {
                        color: "#94a3b8",
                        usePointStyle: true,
                        pointStyle: "circle",
                        padding: 15
                    }
                }
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
registry.category("actions").add("account_management_metrics.dashboard", AccountDashboardMetrics);
