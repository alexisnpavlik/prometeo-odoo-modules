/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class PricelistDashboardMetrics extends Component {
    static template = "pricelist_management_metrics.DashboardTemplate";

    setup() {

        this.state = useState({
            pricelist: "all",
            category: "all",
            product: "all",
            search: "",
            onlyDiff: false,
            page: 1,
            perPage: 15,
            activeTab: "table",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark"
        });

        this.filtersData = useState({
            pricelists: [],
            categories: [],
            products: [],
            products_by_category: {}
        });

        this.metricsData = useState({
            kpis: {
                total_products: 0,
                products_with_override: 0,
                avg_diff_percent: 0,
                max_diff_percent: 0,
                max_diff_product: "—",
                pricelist_count: 0
            },
            top_differences: { labels: [], bases: [], datasets: [] }
        });

        this.tableData = useState({
            columns: [],
            rows: [],
            page: 1,
            pages: 1,
            total: 0
        });

        this.charts = {};

        onWillStart(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
            await this.loadFiltersMetadata();
            await this.refreshData();
        });

        onMounted(() => {
            this.renderDiffChart();
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

    // --- Manejo de Eventos y Inputs ---
    onCategoryChange() {
        // Al cambiar de categoría, reseteamos el producto a "all" si ya no está en la lista filtrada
        const currentProds = this.currentProductsList;
        if (this.state.product !== "all" && !currentProds.includes(this.state.product)) {
            this.state.product = "all";
        }
    }

    switchTab(tab) {
        this.state.activeTab = tab;
        if (tab === "differences") {
            // Re-renderizar gráfico para ajustar dimensiones del canvas
            setTimeout(() => this.renderDiffChart(), 50);
        }
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        setTimeout(() => this.renderDiffChart(), 50);
    }

    async applyFilters() {
        this.state.page = 1;
        await this.refreshData();
    }

    async clearFilters() {
        this.state.pricelist = "all";
        this.state.category = "all";
        this.state.product = "all";
        this.state.search = "";
        this.state.onlyDiff = false;
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

    formatPercent(val) {
        const v = val || 0;
        return `${v > 0 ? "+" : ""}${v.toFixed ? v.toFixed(2) : v}%`;
    }

    getCell(row, colId) {
        return row.prices[String(colId)] || { price: row.precio_base, defined: false, diff: 0 };
    }

    // --- Llamadas RPC a Odoo Controller ---
    async loadFiltersMetadata() {
        try {
            const data = await rpc("/pricelist_management_metrics/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";

        try {
            const metrics = await rpc("/pricelist_management_metrics/metrics", {
                category: this.state.category,
                product: this.state.product,
                pricelist: this.state.pricelist,
                limit: 20
            });
            Object.assign(this.metricsData, metrics);

            await this.loadTable();

            if (this.state.activeTab === "differences") {
                this.renderDiffChart();
            }

            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas de precios:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    async loadTable() {
        try {
            const data = await rpc("/pricelist_management_metrics/price_table", {
                category: this.state.category,
                product: this.state.product,
                search: this.state.search,
                pricelist: this.state.pricelist,
                only_diff: this.state.onlyDiff,
                page: this.state.page,
                per_page: this.state.perPage
            });
            Object.assign(this.tableData, data);
        } catch (e) {
            console.error("Error al cargar tabla comparativa de precios:", e);
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page = 1;

        // Debounce de búsqueda a 350ms
        clearTimeout(this.searchTimeout);
        this.searchTimeout = setTimeout(() => {
            this.loadTable();
        }, 350);
    }

    async onOnlyDiffChange(ev) {
        this.state.onlyDiff = ev.target.checked;
        this.state.page = 1;
        await this.loadTable();
    }

    async prevPage() {
        if (this.state.page > 1) {
            this.state.page--;
            await this.loadTable();
        }
    }

    async nextPage() {
        if (this.state.page < this.tableData.pages) {
            this.state.page++;
            await this.loadTable();
        }
    }

    renderDiffChart() {
        const isLight = this.state.theme === "light";
        const textColor = isLight ? "#475569" : "#94a3b8";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";
        const gridConfig = { color: gridColor, drawBorder: false };

        Chart.defaults.color = textColor;

        const top = this.metricsData.top_differences;
        const shorten = (l) => (l && l.length > 30 ? l.substring(0, 27) + "..." : l);

        const pricelistColors = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.65)" },   // Neon Blue
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.65)" },  // Purple
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.65)" },  // Green/Emerald
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.65)" },  // Amber/Orange
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.65)" },  // Pink
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.65)" }    // Cyan
        ];

        const datasets = (top.datasets || []).map((ds, idx) => {
            const color = pricelistColors[idx % pricelistColors.length];
            return {
                label: ds.pricelist,
                data: ds.values,
                backgroundColor: color.bg,
                borderColor: color.border,
                borderWidth: 1.5,
                borderRadius: 4
            };
        });

        this.createOrUpdateChart("chart-top-differences", "bar", {
            labels: (top.labels || []).map(shorten),
            datasets: datasets
        }, {
            indexAxis: "y",
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
                        padding: 15
                    }
                },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const ds = (top.datasets || [])[context.datasetIndex] || {};
                            const price = (ds.prices || [])[context.dataIndex];
                            const base = (top.bases || [])[context.dataIndex];
                            const diff = context.raw;
                            return ` ${ds.pricelist}: ${this.formatPercent(diff)} (${this.formatCurrency(price)} vs base ${this.formatCurrency(base)})`;
                        }
                    }
                }
            },
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => `${v}%` } },
                y: { grid: { display: false } }
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
registry.category("actions").add("pricelist_management_metrics.dashboard", PricelistDashboardMetrics);
