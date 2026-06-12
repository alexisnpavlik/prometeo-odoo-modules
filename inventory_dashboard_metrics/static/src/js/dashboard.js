/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS } from "@web/core/assets";

class InventoryDashboardMetrics extends Component {
    static template = "inventory_dashboard_metrics.DashboardTemplate";

    setup() {
        this.state = useState({
            company: "all",
            period: "30",
            inventorySearch: "",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark"
        });

        this.filtersData = useState({
            companies: []
        });

        this.metricsData = useState({
            kpis: {
                total_value: 0,
                total_units: 0,
                stockouts: 0,
                low_stock: 0
            },
            category_valuation: [],
            top_movements: { labels: [], values: [] },
            top_value_products: [],
            critical_stock_alerts: [],
            heatmap_companies: [],
            heatmap_data: [],
            dead_stock: { labels: [], values: [], stocks: [] }
        });

        this.charts = {};

        onWillStart(async () => {
            try {
                if (typeof Chart === "undefined") {
                    await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
                }
            } catch (e) {
                console.warn("No se pudo cargar Chart.js desde CDN, intentando usar la versión global/local de Odoo:", e);
            }
            await this.loadFiltersMetadata();
            await this.refreshData();
        });

        onMounted(() => {
            this.renderCharts();
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
    get filteredInventoryAlerts() {
        const query = (this.state.inventorySearch || "").toLowerCase().trim();
        if (!query) {
            return this.metricsData.critical_stock_alerts || [];
        }
        return (this.metricsData.critical_stock_alerts || []).filter(a => 
            (a.producto || "").toLowerCase().includes(query) ||
            (a.categoria || "").toLowerCase().includes(query)
        );
    }

    // --- Manejo de Eventos y Inputs ---
    onInventorySearchInput(ev) {
        this.state.inventorySearch = ev.target.value;
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        setTimeout(() => {
            this.renderCharts();
        }, 50);
    }

    async applyFilters() {
        await this.refreshData();
    }

    async clearFilters() {
        this.state.company = "all";
        this.state.period = "30";
        this.state.inventorySearch = "";
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

    // --- Llamadas RPC a Odoo Controller ---
    async loadFiltersMetadata() {
        try {
            const data = await rpc("/inventory_dashboard_metrics/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";

        try {
            const metrics = await rpc("/inventory_dashboard_metrics/inventory", {
                company: this.state.company,
                period: parseInt(this.state.period) || 30
            });

            Object.assign(this.metricsData, metrics);
            setTimeout(() => this.renderCharts(), 50);

            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas de inventario:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }

    renderCharts() {
        if (typeof Chart === "undefined") {
            console.warn("Chart.js no está cargado. No se renderizarán los gráficos.");
            return;
        }

        const isLight = this.state.theme === "light";
        const textColor = isLight ? "#475569" : "#94a3b8";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";

        const gridConfig = {
            color: gridColor,
            borderColor: "transparent",
            drawBorder: false
        };

        const metrics = this.metricsData;

        // 1. Gráfico de Dead Stock (Horizontal Bar)
        const dead = metrics.dead_stock || { labels: [], values: [], stocks: [] };
        const shortLabels = (dead.labels || []).map(l => l.length > 20 ? l.substring(0, 17) + "..." : l);

        this.createOrUpdateChart("chart-dead-stock", "bar", {
            labels: shortLabels,
            datasets: [{
                label: "Capital Inmovilizado",
                data: dead.values || [],
                backgroundColor: "rgba(245, 158, 11, 0.65)", // Naranja brillante
                borderColor: "#f59e0b",
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
                            const val = context.raw;
                            const fullLabel = dead.labels[context.dataIndex] || "";
                            return ` ${fullLabel}: ${this.formatCurrency(val)} inmovilizados`;
                        },
                        afterLabel: (context) => {
                            const stock = dead.stocks[context.dataIndex] || 0;
                            return ` Existencias: ${stock.toLocaleString()} unidades sin ventas en los últimos ${this.state.period} días.`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: gridConfig,
                    ticks: {
                        callback: (value) => {
                            if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
                            if (value >= 1000) return (value / 1000).toFixed(0) + 'K';
                            return value;
                        }
                    }
                },
                y: { grid: { display: false } }
            }
        });
    }

    createOrUpdateChart(canvasId, type, data, options = {}) {
        if (typeof Chart === "undefined") return;
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext("2d");

        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }

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

registry.category("actions").add("inventory_dashboard_metrics.dashboard", InventoryDashboardMetrics);
