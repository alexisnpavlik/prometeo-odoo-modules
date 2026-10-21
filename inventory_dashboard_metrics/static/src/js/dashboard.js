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

// Orden por columna: null va siempre al final, sin importar el sentido
const compareBy = (key, dir) => (a, b) => {
    const x = a[key];
    const y = b[key];
    if (x === y) return 0;
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    const diff = typeof x === "string" ? x.localeCompare(y, "es") : x - y;
    return dir === "asc" ? diff : -diff;
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
            overPage: 1,
            search: "",
            category: "all",
            vendor: "all",
            restPage: 1,
            buyPage: 1,
            buyCover: "30",
            buyLoading: false,
            // Orden elegido tocando un encabezado: { key, dir } o null para el orden por defecto
            sort: { over: null, rest: null, buy: null },
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
        const q = this.state.search.toLowerCase().trim();
        const { category, vendor } = this.state;
        const rows = this.metricsData.overstock
            .filter((r) =>
                (category === "all" || r.categoria === category) &&
                (vendor === "all" || r.vendor === vendor) &&
                (!q || r.producto.toLowerCase().includes(q)))
            // Orden por defecto: más plata de más primero, igual que el controlador
            .sort((a, b) => b.excess_value - a.excess_value);
        return this.sortRows(rows, "over");
    }

    get filteredRestock() {
        const q = this.state.search.toLowerCase().trim();
        const { category, vendor } = this.state;
        const rows = this.metricsData.restock.filter((r) =>
            (category === "all" || r.categoria === category) &&
            (vendor === "all" || r.vendor === vendor) &&
            (!q || r.producto.toLowerCase().includes(q)));
        return this.sortRows(rows, "rest");
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
                days_after: roundUnits((Math.max(c.stock, 0) + qty) / c.daily),
            });
        }
        return rows.sort((a, b) =>
            (a.status !== "urgente") - (b.status !== "urgente") ||
            (a.vendor === "Sin proveedor") - (b.vendor === "Sin proveedor") ||
            a.vendor.localeCompare(b.vendor) ||
            b.total - a.total);
    }

    get filteredPurchase() {
        const q = this.state.search.toLowerCase().trim();
        const { vendor, category } = this.state;
        const rows = this.purchaseRows.filter((r) =>
            (vendor === "all" || r.vendor === vendor) &&
            (category === "all" || r.categoria === category) &&
            (!q || r.producto.toLowerCase().includes(q)));
        return this.sortRows(rows, "buy");
    }

    sortRows(rows, table) {
        const sort = this.state.sort[table];
        return sort ? [...rows].sort(compareBy(sort.key, sort.dir)) : rows;
    }

    // Indicador del encabezado: flecha si la tabla está ordenada por esa columna
    sortMark(table, key) {
        const sort = this.state.sort[table];
        if (!sort || sort.key !== key) return "";
        return sort.dir === "asc" ? "▲" : "▼";
    }

    get periodDays() {
        return parseInt(this.state.period) || 90;
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

    // Cada click en el encabezado: ascendente → descendente → orden por defecto
    onSortClick(ev) {
        const { table, key } = ev.currentTarget.dataset;
        const sort = this.state.sort[table];
        if (!sort || sort.key !== key) {
            this.state.sort[table] = { key, dir: "asc" };
        } else if (sort.dir === "asc") {
            this.state.sort[table] = { key, dir: "desc" };
        } else {
            this.state.sort[table] = null;
        }
        this.state[`${table}Page`] = 1;
    }

    resetBuyPage() {
        this.state.buyPage = 1;
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

    exportExcel(ev) {
        const table = ev.currentTarget.dataset.table;
        const params = new URLSearchParams({
            table,
            company: this.state.company,
            period: this.state.period,
            vendor: this.state.vendor,
            cover: this.state.buyCover,
            category: this.state.category,
            search: this.state.search,
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
        Object.assign(this.state, { company: "all", period: "90", search: "", category: "all", vendor: "all", showFilters: false });
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
        // Solo visual: el controlador sigue calculando con 3 decimales para no perder los productos de rotación lenta
        return new Intl.NumberFormat("es-AR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(val || 0);
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
