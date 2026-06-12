/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class PosDashboardMetrics extends Component {
    static template = "pos_management_metrics.DashboardTemplate";

    setup() {

        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            pos: "all",
            cashier: "all",
            company: "all",
            category: "all",
            product: "all",
            search: "",
            profitabilitySearch: "",
            page: 1,
            perPage: 15,
            activeTab: "general",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark"
        });

        this.filtersData = useState({
            pos_configs: [],
            cashiers: [],
            companies: [],
            categories: [],
            products: [],
            products_by_category: {},
            min_date: "",
            max_date: ""
        });

        this.metricsData = useState({
            kpis: {
                total_revenue: 0,
                total_revenue_net: 0,
                total_tax: 0,
                total_orders: 0,
                ticket_average: 0,
                cash_difference: 0
            },
            charts: {
                sales_trend: { labels: [], companies: {}, timeframe: "Diario" },
                sales_by_pos: { labels: [], values: [] },
                payment_methods: { labels: [], values: [] },
                top_products: { labels: [], values: [] },
                top_categories: { labels: [], values: [] },
                sales_by_weekday: { labels: [], values: [] },
                sales_by_hour: { labels: [], values: [] }
            },
            profitability: {
                product_margins: [],
                category_margins: [],
                mom_growth_revenue: 0.0,
                yoy_growth_revenue: 0.0,
                unidades_por_ticket: 0.0,
                total_cost: 0.0,
                gross_profit: 0.0,
                margin_percent: 0.0,
                top_profitable: [],
                bottom_profitable: []
            }
        });

        this.sessionsData = useState([]);
        
        this.transactionsData = useState({
            sales: [],
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

    // --- Getters Reactivos ---
    get currentProductsList() {
        const cat = this.state.category;
        if (cat && cat !== "all" && this.filtersData.products_by_category[cat]) {
            return this.filtersData.products_by_category[cat];
        }
        return this.filtersData.products;
    }

    get filteredProductMargins() {
        const search = (this.state.profitabilitySearch || "").toLowerCase().trim();
        if (!search) return this.metricsData.profitability.product_margins || [];
        return (this.metricsData.profitability.product_margins || []).filter(p => 
            p.producto && p.producto.toLowerCase().includes(search)
        );
    }

    // --- Manejo de Eventos y Inputs ---
    onProfitabilitySearchInput(ev) {
        this.state.profitabilitySearch = ev.target.value;
    }
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

    onCategoryChange() {
        // Al cambiar de categoría, reseteamos el producto a "all" si ya no está en la lista filtrada
        const currentProds = this.currentProductsList;
        if (this.state.product !== "all" && !currentProds.includes(this.state.product)) {
            this.state.product = "all";
        }
    }

    switchTab(tab) {
        this.state.activeTab = tab;
        this.state.page = 1;

        // Carga diferida según pestaña activa
        if (tab === "sessions") {
            this.loadSessions();
        } else if (tab === "transactions") {
            this.loadTransactions();
        } else if (tab === "general") {
            // Re-renderizar gráficos en pestaña general para ajustar dimensiones
            setTimeout(() => this.renderAllCharts(), 50);
        }
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        setTimeout(() => {
            this.renderAllCharts();
            if (this.state.activeTab === "sessions") {
                this.loadSessions();
            }
        }, 50);
    }

    async applyFilters() {
        this.state.page = 1;
        await this.refreshData();
    }

    async clearFilters() {
        this.state.preset = "30days";
        this.setPresetDates("30days");
        this.state.pos = "all";
        this.state.cashier = "all";
        this.state.company = "all";
        this.state.category = "all";
        this.state.product = "all";
        this.state.search = "";
        this.state.profitabilitySearch = "";
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

    formatDatetime(dt) {
        if (!dt) return "—";
        const parts = dt.split(" ");
        if (parts.length < 2) return dt;
        const dParts = parts[0].split("-");
        const tParts = parts[1].split(":");
        return `${dParts[2]}/${dParts[1]}/${dParts[0]} ${tParts[0]}:${tParts[1]}`;
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
    async loadFiltersMetadata() {
        try {
            const data = await rpc("/pos_management_metrics/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData(force = false) {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";

        try {
            const metrics = await rpc("/pos_management_metrics/metrics", {
                start_date: this.state.startDate || null,
                end_date: this.state.endDate || null,
                pos: this.state.pos,
                cashier: this.state.cashier,
                company: this.state.company,
                category: this.state.category,
                product: this.state.product
            });

            Object.assign(this.metricsData, metrics);

            if (this.state.activeTab === "general") {
                this.renderAllCharts();
            } else if (this.state.activeTab === "sessions") {
                await this.loadSessions();
            } else if (this.state.activeTab === "transactions") {
                await this.loadTransactions();
            }

            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    async loadSessions() {
        try {
            const data = await rpc("/pos_management_metrics/sessions", {});
            this.sessionsData.length = 0;
            this.sessionsData.push(...data.sessions);

            // Renderizar gráfico de aperturas/cierres en pestaña Auditoría
            setTimeout(() => this.renderSessionsChart(data.sessions), 50);
        } catch (e) {
            console.error("Error al cargar auditoría de cajas:", e);
        }
    }

    async loadTransactions() {
        try {
            const data = await rpc("/pos_management_metrics/raw_sales", {
                start_date: this.state.startDate || null,
                end_date: this.state.endDate || null,
                pos: this.state.pos,
                cashier: this.state.cashier,
                company: this.state.company,
                category: this.state.category,
                product: this.state.product,
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage
            });
            Object.assign(this.transactionsData, data);
        } catch (e) {
            console.error("Error al cargar transacciones:", e);
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page = 1;
        
        // Debounce de búsqueda a 350ms
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => {
            this.loadTransactions();
        }, 350);
    }

    async prevPage() {
        if (this.state.page > 1) {
            this.state.page--;
            await this.loadTransactions();
        }
    }

    async nextPage() {
        if (this.state.page < this.transactionsData.pages) {
            this.state.page++;
            await this.loadTransactions();
        }
    }

    exportCSV() {
        // Redireccionar al endpoint de tipo HTTP de exportación pasándole filtros GET
        const params = new URLSearchParams({
            start_date: this.state.startDate || '',
            end_date: this.state.endDate || '',
            pos: this.state.pos,
            cashier: this.state.cashier,
            company: this.state.company,
            category: this.state.category,
            product: this.state.product
        });
        window.open(`/pos_management_metrics/export?${params.toString()}`, '_blank');
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

        // 1. Tendencia de Ventas (Spline/Line) - Una línea por empresa
        const trendData = this.metricsData.charts.sales_trend;
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
                label: "Ingresos",
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

        this.createOrUpdateChart("chart-sales-trend", "line", {
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

        // 2. Métodos de Pago (Horizontal Bar - Porcentual)
        const payValues = this.metricsData.charts.payment_methods.values;
        const totalPayment = payValues.reduce((a, b) => a + b, 0);
        const paymentLabels = this.metricsData.charts.payment_methods.labels.map((l) => {
            const shortLabel = l.length > 18 ? l.substring(0, 15) + "..." : l;
            return shortLabel;
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

        // 3. Top Productos (Horizontal Bar)
        this.createOrUpdateChart("chart-top-products", "bar", {
            labels: this.metricsData.charts.top_products.labels.map(l => l.length > 25 ? l.substring(0, 22) + "..." : l),
            datasets: [{
                label: "Total Ventas",
                data: this.metricsData.charts.top_products.values,
                backgroundColor: "rgba(59, 130, 246, 0.65)",
                borderColor: "#3b82f6",
                borderWidth: 1.5,
                borderRadius: 4
            }]
        }, {
            indexAxis: "y",
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
                y: { grid: { display: false } }
            }
        });

        // 4. Top Categorías (Horizontal Bar)
        this.createOrUpdateChart("chart-top-categories", "bar", {
            labels: this.metricsData.charts.top_categories.labels.map(l => l.length > 20 ? l.substring(0, 17) + "..." : l),
            datasets: [{
                label: "Total Ventas",
                data: this.metricsData.charts.top_categories.values,
                backgroundColor: "rgba(139, 92, 246, 0.65)",
                borderColor: "#8b5cf6",
                borderWidth: 1.5,
                borderRadius: 4
            }]
        }, {
            indexAxis: "y",
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => this.formatCurrency(v).split(",")[0] } },
                y: { grid: { display: false } }
            }
        });

        // 5. Ventas por Día de la Semana (Bar)
        this.createOrUpdateChart("chart-sales-by-weekday", "bar", {
            labels: this.metricsData.charts.sales_by_weekday.labels,
            datasets: [{
                label: "Ingresos",
                data: this.metricsData.charts.sales_by_weekday.values,
                backgroundColor: "rgba(139, 92, 246, 0.65)",
                borderColor: "#8b5cf6",
                borderWidth: 1.5,
                borderRadius: 6
            }]
        }, {
            scales: {
                x: { grid: { display: false } },
                y: { grid: gridConfig }
            }
        });

        // 6. Distribución Horaria (Line)
        this.createOrUpdateChart("chart-sales-by-hour", "line", {
            labels: this.metricsData.charts.sales_by_hour.labels,
            datasets: [{
                label: "Vendido",
                data: this.metricsData.charts.sales_by_hour.values,
                borderColor: "#f59e0b",
                backgroundColor: "rgba(245, 158, 11, 0.05)",
                fill: true,
                borderWidth: 2,
                tension: 0.3,
                pointRadius: 2
            }]
        }, {
            scales: {
                x: { grid: { display: false } },
                y: { grid: gridConfig }
            }
        });
    }

    renderSessionsChart(sessions) {
        const aperturas = new Array(24).fill(0);
        const cierres = new Array(24).fill(0);

        sessions.forEach(s => {
            if (s.apertura) {
                const h = new Date(s.apertura.replace(" ", "T")).getHours();
                if (!isNaN(h)) aperturas[h]++;
            }
            if (s.cierre) {
                const h = new Date(s.cierre.replace(" ", "T")).getHours();
                if (!isNaN(h)) cierres[h]++;
            }
        });

        const labels = Array.from({ length: 24 }, (_, i) => `${i}:00`);
        const isLight = this.state.theme === "light";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";
        const gridConfig = { color: gridColor, drawBorder: false };

        this.createOrUpdateChart("chart-session-hours", "bar", {
            labels: labels,
            datasets: [
                {
                    label: "Aperturas",
                    data: aperturas,
                    backgroundColor: "rgba(16, 185, 129, 0.65)",
                    borderColor: "#10b981",
                    borderWidth: 1.5,
                    borderRadius: 4
                },
                {
                    label: "Cierres",
                    data: cierres,
                    backgroundColor: "rgba(245, 158, 11, 0.65)",
                    borderColor: "#f59e0b",
                    borderWidth: 1.5,
                    borderRadius: 4
                }
            ]
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: "#94a3b8" } } },
            scales: {
                x: { grid: { display: false } },
                y: { grid: gridConfig, beginAtZero: true, ticks: { precision: 0, color: "#94a3b8" } }
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
registry.category("actions").add("pos_management_metrics.dashboard", PosDashboardMetrics);
