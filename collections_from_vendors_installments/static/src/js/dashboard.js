/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, onMounted, useState, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { loadJS, loadCSS } from "@web/core/assets";

class CviDashboard extends Component {
    static template = "collections_from_vendors_installments.DashboardTemplate";

    setup() {
        this.state = useState({
            preset: "30days",
            startDate: "",
            endDate: "",
            company: "all",
            search: "",
            page: 1,
            perPage: 15,
            activeTab: "general",
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
        });

        this.filtersData = useState({ companies: [], min_date: "", max_date: "" });

        this.metricsData = useState({
            kpis: {
                sold: 0,
                card_count: 0,
                residual: 0,
                collected: 0,
                payment_count: 0,
                overdue_amount: 0,
                overdue_installments: 0,
                overdue_rate: 0,
                recovered_count: 0,
                to_recover_count: 0,
            },
            charts: {
                sales_by_vendor: { labels: [], vendors: {} },
                portfolio_by_collector: { labels: [], residual: [], overdue: [], collected: [] },
                aging: { labels: [], values: [] },
                settlement_differences: { labels: [], values: [], counts: [] },
                vendor_stock: { labels: [], values: [] },
            },
            map_points: [],
        });

        this.cardsData = useState({ records: [], page: 1, pages: 1, total: 0 });
        this.installmentsData = useState({ records: [], page: 1, pages: 1, total: 0 });

        this.charts = {};
        this.map = null;
        this.markerLayer = null;

        onWillStart(async () => {
            await loadJS("https://cdn.jsdelivr.net/npm/chart.js");
            // Leaflet para el mapa de ventas por ubicación que pide HU-32. Chart.js no
            // dibuja mapas: lo más parecido sería un scatter de latitud contra
            // longitud, que no le sirve a nadie para reconocer un barrio.
            await loadCSS("https://unpkg.com/leaflet@1.9.4/dist/leaflet.css");
            await loadJS("https://unpkg.com/leaflet@1.9.4/dist/leaflet.js");
            this.setPresetDates(this.state.preset);
            await this.loadFiltersMetadata();
            await this.refreshData();
        });

        onMounted(() => {
            this.renderAllCharts();
        });

        onWillUnmount(() => {
            Object.values(this.charts).forEach((chart) => chart && chart.destroy());
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
    }

    // --- Eventos ---
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
        if (tab === "cards" || tab === "installments") {
            this.loadRecords(tab);
        } else if (tab === "general") {
            setTimeout(() => this.renderAllCharts(), 50);
        } else if (tab === "map") {
            // El contenedor recién tiene tamaño cuando la pestaña es visible; sin el
            // respiro, Leaflet calcula mal el alto y el mapa queda en una franja.
            setTimeout(() => this.renderMap(), 80);
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
        this.state.search = "";
        this.state.page = 1;
        await this.refreshData();
    }

    formatCurrency(val) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency",
            currency: "ARS",
            minimumFractionDigits: 2,
        }).format(val || 0);
    }

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
            return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        };
        this.state.startDate = formatDate(start);
        this.state.endDate = formatDate(end);
    }

    getFilterPayload() {
        return {
            start_date: this.state.startDate || null,
            end_date: this.state.endDate || null,
            company: this.state.company,
        };
    }

    async loadFiltersMetadata() {
        try {
            const data = await rpc("/collections_from_vendors_installments/filters", {});
            Object.assign(this.filtersData, data);
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const metrics = await rpc(
                "/collections_from_vendors_installments/metrics",
                this.getFilterPayload()
            );
            Object.assign(this.metricsData, metrics);
            if (this.state.activeTab === "general") {
                this.renderAllCharts();
            } else if (this.state.activeTab === "map") {
                this.renderMap();
            } else {
                await this.loadRecords(this.state.activeTab);
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
            const data = await rpc("/collections_from_vendors_installments/records", {
                ...this.getFilterPayload(),
                model: model,
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage,
            });
            const target = model === "installments" ? this.installmentsData : this.cardsData;
            Object.assign(target, data);
        } catch (e) {
            console.error(`Error al cargar ${model}:`, e);
        }
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page = 1;
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
        const target = this.state.activeTab === "installments" ? this.installmentsData : this.cardsData;
        if (this.state.page < target.pages) {
            this.state.page++;
            await this.loadRecords(this.state.activeTab);
        }
    }

    exportCSV() {
        const params = new URLSearchParams({
            model: this.state.activeTab === "installments" ? "installments" : "cards",
            start_date: this.state.startDate || "",
            end_date: this.state.endDate || "",
            company: this.state.company,
            search: this.state.search || "",
        });
        window.open(
            `/collections_from_vendors_installments/export?${params.toString()}`,
            "_blank"
        );
    }

    // --- Mapa (HU-32) ---
    renderMap() {
        if (typeof L === "undefined") return;
        const container = document.getElementById("cvi-map");
        if (!container) return;
        if (!this.map) {
            this.map = L.map(container).setView([-27.45, -58.98], 12);
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                attribution: "© OpenStreetMap",
                maxZoom: 19,
            }).addTo(this.map);
            this.markerLayer = L.layerGroup().addTo(this.map);
        }
        this.markerLayer.clearLayers();
        const points = this.metricsData.map_points || [];
        const bounds = [];
        points.forEach((p) => {
            const marker = L.circleMarker([p.lat, p.lng], {
                radius: 7,
                color: p.residual > 0 ? "#ef4444" : "#10b981",
                fillColor: p.residual > 0 ? "#ef4444" : "#10b981",
                fillOpacity: 0.6,
                weight: 2,
            });
            marker.bindPopup(
                `<strong>${p.partner}</strong><br/>${p.name} · ${p.state}<br/>` +
                `Vendedor: ${p.vendor}<br/>Saldo: ${this.formatCurrency(p.residual)}`
            );
            marker.addTo(this.markerLayer);
            bounds.push([p.lat, p.lng]);
        });
        if (bounds.length) {
            this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
        }
        this.map.invalidateSize();
    }

    renderAllCharts() {
        if (this.state.activeTab !== "general") return;

        const isLight = this.state.theme === "light";
        const textColor = isLight ? "#475569" : "#94a3b8";
        const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)";
        Chart.defaults.color = textColor;
        const gridConfig = { color: gridColor, borderColor: "transparent", drawBorder: false };
        const money = (v) => this.formatCurrency(v).split(",")[0];

        // 1. Ventas por vendedor y por período.
        const sales = this.metricsData.charts.sales_by_vendor;
        const vendors = sales.vendors || {};
        const palette = [
            { border: "#3b82f6", bg: "rgba(59, 130, 246, 0.08)" },
            { border: "#a855f7", bg: "rgba(168, 85, 247, 0.08)" },
            { border: "#10b981", bg: "rgba(16, 185, 129, 0.08)" },
            { border: "#f59e0b", bg: "rgba(245, 158, 11, 0.08)" },
            { border: "#ec4899", bg: "rgba(236, 72, 153, 0.08)" },
            { border: "#06b6d4", bg: "rgba(6, 182, 212, 0.08)" },
        ];
        const datasets = Object.keys(vendors).map((name, idx) => {
            const color = palette[idx % palette.length];
            return {
                label: name,
                data: vendors[name],
                borderColor: color.border,
                backgroundColor: color.bg,
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointBackgroundColor: color.border,
                pointHoverRadius: 6,
            };
        });
        this.createOrUpdateChart("chart-sales-by-vendor", "line", {
            labels: sales.labels,
            datasets: datasets.length ? datasets : [{ label: "Ventas", data: [], borderColor: "#3b82f6" }],
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: textColor, usePointStyle: true, pointStyle: "circle", padding: 15 } } },
            scales: { x: { grid: gridConfig }, y: { grid: gridConfig, ticks: { callback: money } } },
        });

        // 2. Cartera por cobrador.
        const portfolio = this.metricsData.charts.portfolio_by_collector;
        this.createOrUpdateChart("chart-portfolio", "bar", {
            labels: portfolio.labels,
            datasets: [
                { label: "Saldo", data: portfolio.residual, backgroundColor: "rgba(59, 130, 246, 0.65)", borderColor: "#3b82f6", borderWidth: 1.5, borderRadius: 4 },
                { label: "Cobrado", data: portfolio.collected, backgroundColor: "rgba(16, 185, 129, 0.65)", borderColor: "#10b981", borderWidth: 1.5, borderRadius: 4 },
                { label: "Mora", data: portfolio.overdue, backgroundColor: "rgba(239, 68, 68, 0.65)", borderColor: "#ef4444", borderWidth: 1.5, borderRadius: 4 },
            ],
        }, {
            plugins: { legend: { display: true, position: "top", labels: { color: textColor, usePointStyle: true, pointStyle: "circle", padding: 15 } } },
            scales: { x: { grid: { display: false } }, y: { grid: gridConfig, ticks: { callback: money } } },
        });

        // 3. Antigüedad de deuda.
        this.createOrUpdateChart("chart-aging", "bar", {
            labels: this.metricsData.charts.aging.labels,
            datasets: [{
                label: "Deuda vencida",
                data: this.metricsData.charts.aging.values,
                backgroundColor: ["rgba(245, 158, 11, 0.55)", "rgba(249, 115, 22, 0.6)", "rgba(239, 68, 68, 0.65)", "rgba(153, 27, 27, 0.7)"],
                borderColor: ["#f59e0b", "#f97316", "#ef4444", "#991b1b"],
                borderWidth: 1.5,
                borderRadius: 6,
            }],
        }, {
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${this.formatCurrency(ctx.raw)}` } } },
            scales: { x: { grid: { display: false } }, y: { grid: gridConfig, ticks: { callback: money } } },
        });

        // 4. Rendiciones con diferencias.
        this.createOrUpdateChart("chart-settlement-diff", "bar", {
            labels: this.metricsData.charts.settlement_differences.labels,
            datasets: [{
                label: "Diferencia acumulada",
                data: this.metricsData.charts.settlement_differences.values,
                backgroundColor: "rgba(239, 68, 68, 0.65)",
                borderColor: "#ef4444",
                borderWidth: 1.5,
                borderRadius: 4,
            }],
        }, {
            indexAxis: "y",
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${this.formatCurrency(ctx.raw)}` } } },
            scales: { x: { grid: gridConfig, ticks: { callback: money } }, y: { grid: { display: false } } },
        });

        // 5. Mercadería en poder de vendedores.
        this.createOrUpdateChart("chart-vendor-stock", "bar", {
            labels: this.metricsData.charts.vendor_stock.labels.map((l) => (l.length > 22 ? l.substring(0, 19) + "..." : l)),
            datasets: [{
                label: "Unidades",
                data: this.metricsData.charts.vendor_stock.values,
                backgroundColor: "rgba(139, 92, 246, 0.65)",
                borderColor: "#8b5cf6",
                borderWidth: 1.5,
                borderRadius: 4,
            }],
        }, {
            indexAxis: "y",
            plugins: { legend: { display: false } },
            scales: { x: { grid: gridConfig }, y: { grid: { display: false } } },
        });
    }

    createOrUpdateChart(canvasId, type, data, options = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
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
                    bodyColor: "#94a3b8",
                },
            },
        };
        if (options.plugins) {
            Object.assign(mergedOptions.plugins, options.plugins);
            delete options.plugins;
        }
        Object.assign(mergedOptions, options);
        this.charts[canvasId] = new Chart(ctx, { type, data, options: mergedOptions });
    }
}

registry.category("actions").add("collections_from_vendors_installments.dashboard", CviDashboard);
