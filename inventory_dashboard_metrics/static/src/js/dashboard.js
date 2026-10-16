/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

const PAGE_SIZE = 25;
const LOW_COVER_DAYS = 15;
// Umbral fijo de sobrestock: debe coincidir con DEFAULT_TARGET del controlador
const OVERSTOCK_DAYS = 90;

// Mismo redondeo y misma cuenta que _purchase_rows en el controlador
const roundUnits = (value) => Math.floor(value + 0.5);

// Etiqueta de la barra "Cantidad a comprar" según los días de venta a cubrir
const BUY_COVER_LEVELS = [
    [15, "Poca"],
    [45, "Normal"],
    [75, "Bastante"],
    [120, "Mucha"],
    [Infinity, "Muchísima"],
];

const OVER_SORTS = {
    excess: (a, b) => b.excess_value - a.excess_value,
    value: (a, b) => b.value - a.value,
    stock: (a, b) => b.stock - a.stock,
    idle: (a, b) => (b.days_since_sale ?? 1e9) - (a.days_since_sale ?? 1e9),
};

class InventoryDashboardMetrics extends Component {
    static template = "inventory_dashboard_metrics.DashboardTemplate";

    setup() {
        this.lowCoverDays = LOW_COVER_DAYS;
        this.overstockDays = OVERSTOCK_DAYS;
        this.state = useState({
            company: "all",
            period: "90",
            tab: "stock",
            showFilters: false,
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
            overSearch: "",
            overStatus: "all",
            overSort: "excess",
            overPage: 1,
            restSearch: "",
            restStatus: "all",
            category: "all",
            vendor: "all",
            restPage: 1,
            buySearch: "",
            buyStatus: "all",
            buyPage: 1,
            buyCover: "30",
            buyLoading: false,
        });

        this.filtersData = useState({ companies: [] });

        this.metricsData = useState({
            overstock_total: 0,
            excess_value: 0,
            overstock: [],
            restock_total: 0,
            restock: [],
        });

        this.purchaseData = useState({ rows: [] });
        this.purchaseStale = true;

        onWillStart(async () => {
            await this.loadFiltersMetadata();
            await this.refreshData();
        });
    }

    // --- Listas filtradas ---
    categoriesOf(rows) {
        return [...new Set(rows.map((r) => r.categoria))].sort();
    }

    get categories() {
        return this.categoriesOf([...this.metricsData.overstock, ...this.metricsData.restock]);
    }

    get filteredOverstock() {
        const q = this.state.overSearch.toLowerCase().trim();
        const { overStatus, category, vendor, overSort } = this.state;
        return this.metricsData.overstock
            .filter((r) =>
                (overStatus === "all" || r.status === overStatus) &&
                (category === "all" || r.categoria === category) &&
                (vendor === "all" || r.vendor === vendor) &&
                (!q || r.producto.toLowerCase().includes(q)))
            .sort(OVER_SORTS[overSort]);
    }

    get filteredRestock() {
        const q = this.state.restSearch.toLowerCase().trim();
        const { restStatus, category, vendor } = this.state;
        return this.metricsData.restock.filter((r) =>
            (restStatus === "all" || r.status === restStatus) &&
            (category === "all" || r.categoria === category) &&
            (vendor === "all" || r.vendor === vendor) &&
            (!q || r.producto.toLowerCase().includes(q)));
    }

    get overFilteredExcess() {
        return this.filteredOverstock.reduce((sum, r) => sum + r.excess_value, 0);
    }

    get vendors() {
        const rows = [...this.metricsData.overstock, ...this.metricsData.restock, ...this.purchaseData.rows];
        return [...new Set(rows.map((r) => r.vendor))].sort();
    }

    get purchaseRows() {
        const cover = parseInt(this.state.buyCover) || 30;
        const rows = [];
        for (const c of this.purchaseData.rows) {
            const qty = roundUnits(c.daily * cover - Math.max(c.stock, 0));
            if (qty <= 0) {
                continue;
            }
            rows.push({
                ...c,
                qty,
                total: qty * c.price,
                min_qty: c.supplier_min > qty ? c.supplier_min : 0,
            });
        }
        return rows.sort((a, b) =>
            (a.status !== "urgente") - (b.status !== "urgente") ||
            (a.vendor === "Sin proveedor") - (b.vendor === "Sin proveedor") ||
            a.vendor.localeCompare(b.vendor) ||
            b.total - a.total);
    }

    get filteredPurchase() {
        const q = this.state.buySearch.toLowerCase().trim();
        const { buyStatus, vendor, category } = this.state;
        return this.purchaseRows.filter((r) =>
            (buyStatus === "all" || r.status === buyStatus) &&
            (vendor === "all" || r.vendor === vendor) &&
            (category === "all" || r.categoria === category) &&
            (!q || r.producto.toLowerCase().includes(q)));
    }

    get buyCoverLabel() {
        const days = parseInt(this.state.buyCover) || 30;
        return BUY_COVER_LEVELS.find(([limit]) => days <= limit)[1];
    }

    get buyFilteredUnits() {
        return this.filteredPurchase.reduce((sum, r) => sum + r.qty, 0);
    }

    get buyNoPrice() {
        return this.filteredPurchase.filter((r) => !r.price).length;
    }

    get buyFilteredTotal() {
        return this.filteredPurchase.reduce((sum, r) => sum + r.total, 0);
    }

    get buyPage() {
        return this.pageOf(this.filteredPurchase, this.state.buyPage);
    }

    pageOf(rows, page) {
        const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
        const current = Math.min(page, pages);
        return { rows: rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE), current, pages };
    }

    get overPage() {
        return this.pageOf(this.filteredOverstock, this.state.overPage);
    }

    get restPage() {
        return this.pageOf(this.filteredRestock, this.state.restPage);
    }

    // --- Eventos ---
    onCategoryChange() {
        Object.assign(this.state, { overPage: 1, restPage: 1, buyPage: 1 });
    }

    async onTabClick(ev) {
        this.state.tab = ev.currentTarget.dataset.tab;
        if (this.state.tab === "compra" && this.purchaseStale) {
            await this.loadPurchase();
        }
    }

    resetBuyPage() {
        this.state.buyPage = 1;
    }

    clearBuyFilters() {
        Object.assign(this.state, { buySearch: "", buyStatus: "all", buyPage: 1 });
    }

    resetOverPage() {
        this.state.overPage = 1;
    }

    resetRestPage() {
        this.state.restPage = 1;
    }

    changePage(ev) {
        const { key, dir } = ev.currentTarget.dataset;
        this.state[key] = Math.max(1, this.state[key] + parseInt(dir));
    }

    clearOverFilters() {
        Object.assign(this.state, { overSearch: "", overStatus: "all", overSort: "excess", overPage: 1 });
    }

    clearRestFilters() {
        Object.assign(this.state, { restSearch: "", restStatus: "all", restPage: 1 });
    }

    exportExcel(ev) {
        const table = ev.currentTarget.dataset.table;
        const over = table === "overstock";
        const buy = table === "purchase";
        const params = new URLSearchParams({
            table,
            company: this.state.company,
            period: this.state.period,
            vendor: this.state.vendor,
            cover: this.state.buyCover,
            status: buy ? this.state.buyStatus : over ? this.state.overStatus : this.state.restStatus,
            category: this.state.category,
            search: buy ? this.state.buySearch : over ? this.state.overSearch : this.state.restSearch,
            sort: this.state.overSort,
        });
        window.open(`/inventory_dashboard_metrics/export?${params.toString()}`, "_blank");
    }

    toggleFilters() {
        this.state.showFilters = !this.state.showFilters;
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
    }

    async applyFilters() {
        this.state.showFilters = false;
        await this.refreshData();
    }

    async clearFilters() {
        Object.assign(this.state, { company: "all", period: "90", category: "all", vendor: "all", showFilters: false });
        await this.refreshData();
    }

    // --- Formateadores ---
    formatCurrency(val) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency", currency: "ARS", maximumFractionDigits: 0,
        }).format(val || 0);
    }

    // Color de "Alcanza para": rojo se agota, ámbar poco, verde bien, violeta sobra (más de 90 días)
    coverClass(days) {
        if (days === null || days === undefined) return "cover-pill none";
        if (days <= LOW_COVER_DAYS) return "cover-pill low";
        if (days <= 45) return "cover-pill mid";
        if (days <= OVERSTOCK_DAYS) return "cover-pill ok";
        return "cover-pill over";
    }

    formatDaily(val) {
        return new Intl.NumberFormat("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val || 0);
    }

    formatNumber(val) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(val || 0);
    }

    // --- RPC ---
    async loadFiltersMetadata() {
        try {
            Object.assign(this.filtersData, await rpc("/inventory_dashboard_metrics/filters", {}));
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async loadPurchase() {
        this.state.buyLoading = true;
        try {
            const data = await rpc("/inventory_dashboard_metrics/purchase", {
                company: this.state.company,
                period: parseInt(this.state.period) || 90,
            });
            Object.assign(this.purchaseData, data);
            this.state.buyPage = 1;
            this.purchaseStale = false;
        } catch (e) {
            console.error("Error al calcular la recomendación de compra:", e);
        } finally {
            this.state.buyLoading = false;
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const metrics = await rpc("/inventory_dashboard_metrics/inventory", {
                company: this.state.company,
                period: parseInt(this.state.period) || 90,
            });
            Object.assign(this.metricsData, metrics);
            Object.assign(this.state, { overPage: 1, restPage: 1 });
            if (!this.categories.includes(this.state.category)) {
                this.state.category = "all";
            }
            if (!this.vendors.includes(this.state.vendor)) {
                this.state.vendor = "all";
            }
            this.purchaseStale = true;
            if (this.state.tab === "compra") {
                await this.loadPurchase();
            }
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas de inventario:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("actions").add("inventory_dashboard_metrics.dashboard", InventoryDashboardMetrics);
