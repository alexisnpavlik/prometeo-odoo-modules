/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useExternalListener, useState } from "@odoo/owl";
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

// Estados por pestaña: valor, etiqueta, color de la tarjeta
const STATUSES = {
    stock: [
        ["sin_stock", "Sin stock", "red"],
        ["por_agotarse", "Por agotarse", "amber"],
        ["sin_venta", "Sin ventas", "purple"],
        ["sobrestock", "Sobrestock", "blue"],
    ],
    compra: [
        ["urgente", "Urgente", "red"],
        ["normal", "Normal", "amber"],
    ],
};
const PERIOD_PRESETS = ["30", "60", "90", "180", "365"];
const RESTOCK_STATUSES = ["sin_stock", "por_agotarse"];
const OVERSTOCK_STATUSES = ["sin_venta", "sobrestock"];

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
        this.periodPresets = PERIOD_PRESETS;
        this.state = useState({
            company: [],
            period: "90",
            tab: "stock",
            showFilters: false,
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
            overPage: 1,
            product: [],
            category: [],
            vendor: [],
            status: [],
            // Multi-selección abierta y el texto de búsqueda de cada una
            openFilter: null,
            filterSearch: { company: "", category: "", vendor: "", status: "", product: "" },
            restPage: 1,
            buyPage: 1,
            buyCover: "30",
            buyLoading: false,
            // Orden elegido tocando un encabezado: { key, dir } o null para el orden por defecto
            sort: { over: null, rest: null, buy: null },
        });

        // Lo que se edita en la barra lateral: pasa a state recién con "Aplicar", como en los demás dashboards
        this.draft = useState(this.pickFilters(this.state));

        // Cierra el panel de checkboxes al hacer clic fuera del filtro
        useExternalListener(window, "click", () => {
            this.state.openFilter = null;
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

    // Copia de los filtros: las listas se duplican para que el borrador no edite el estado aplicado
    pickFilters({ company, period, product, category, vendor, status }) {
        return { company: [...company], period, product: [...product], category: [...category], vendor: [...vendor], status: [...status] };
    }

    // --- Listas filtradas ---
    categoriesOf(rows) {
        return [...new Set(rows.map((r) => r.categoria))].sort();
    }

    get categories() {
        return this.categoriesOf([...this.metricsData.overstock, ...this.metricsData.restock]);
    }

    // Productos para el filtro: sólo los de las categorías elegidas en el borrador, como en pos_management_metrics
    get products() {
        const { category } = this.draft;
        const rows = [...this.metricsData.overstock, ...this.metricsData.restock, ...this.purchaseData.rows]
            .filter((r) => !category.length || category.includes(r.categoria));
        return [...new Set(rows.map((r) => r.producto))].sort((a, b) => a.localeCompare(b, "es"));
    }

    // Filtros de producto, categoría y proveedor: sin el estado, para que las tarjetas cuenten todos
    baseFilter(rows) {
        const { category, vendor, product } = this.state;
        return rows.filter((r) =>
            (!category.length || category.includes(r.categoria)) &&
            (!vendor.length || vendor.includes(r.vendor)) &&
            (!product.length || product.includes(r.producto)));
    }

    byStatus(rows) {
        const { status } = this.state;
        return status.length ? rows.filter((r) => status.includes(r.status)) : rows;
    }

    get filteredOverstock() {
        const rows = this.byStatus(this.baseFilter(this.metricsData.overstock))
            // Orden por defecto: más plata de más primero, igual que el controlador
            .sort((a, b) => b.excess_value - a.excess_value);
        return this.sortRows(rows, "over");
    }

    get filteredRestock() {
        return this.sortRows(this.byStatus(this.baseFilter(this.metricsData.restock)), "rest");
    }

    get statusOptions() {
        return STATUSES[this.state.tab];
    }

    // Una tabla se oculta si el estado elegido no puede aparecer en ella
    get showRestock() {
        const { status } = this.state;
        return !status.length || status.some((s) => RESTOCK_STATUSES.includes(s));
    }

    get showOverstock() {
        const { status } = this.state;
        return !status.length || status.some((s) => OVERSTOCK_STATUSES.includes(s));
    }

    // --- Multi-selección (mismo control que pos_management_metrics) ---
    filterOptions(field) {
        if (field === "company") return this.filtersData.companies.map((c) => [c, c]);
        if (field === "category") return this.categories.map((c) => [c, c]);
        if (field === "vendor") return this.vendors.map((v) => [v, v]);
        if (field === "product") return this.products.map((p) => [p, p]);
        return this.statusOptions.map(([key, label]) => [key, label]);
    }

    visibleOptions(field) {
        const term = this.state.filterSearch[field].toLowerCase().trim();
        const options = this.filterOptions(field);
        return term ? options.filter(([, label]) => label.toLowerCase().includes(term)) : options;
    }

    multiLabel(field, emptyLabel, pluralLabel) {
        const selection = this.draft[field];
        if (!selection.length) return emptyLabel;
        if (selection.length === 1) {
            const option = this.filterOptions(field).find(([value]) => value === selection[0]);
            return option ? option[1] : selection[0];
        }
        return `${selection.length} ${pluralLabel}`;
    }

    toggleFilterPanel(field) {
        this.state.openFilter = this.state.openFilter === field ? null : field;
    }

    isFilterSelected(field, value) {
        return this.draft[field].includes(value);
    }

    toggleFilterValue(field, value) {
        const selection = this.draft[field];
        const idx = selection.indexOf(value);
        if (idx === -1) {
            selection.push(value);
        } else {
            selection.splice(idx, 1);
        }
        if (field === "category") {
            this.pruneDraftProducts();
        }
    }

    selectAllFilterValues(field) {
        this.draft[field] = [];
        if (field === "category") {
            this.pruneDraftProducts();
        }
    }

    // Al cambiar de categoría se descartan los productos que ya no están en la lista
    pruneDraftProducts() {
        const products = this.products;
        this.draft.product = this.draft.product.filter((p) => products.includes(p));
    }

    onFilterSearchInput(field, ev) {
        this.state.filterSearch[field] = ev.target.value;
    }

    onPresetClick(ev) {
        this.draft.period = ev.currentTarget.dataset.period;
    }

    // Tarjetas por estado: cantidad de productos y plata (de más en stock, a comprar en compra)
    get statusCards() {
        const isBuy = this.state.tab === "compra";
        const rows = isBuy
            ? this.baseFilter(this.purchaseRows)
            : this.baseFilter([...this.metricsData.restock, ...this.metricsData.overstock]);
        return STATUSES[this.state.tab].map(([key, label, color]) => {
            const matched = rows.filter((r) => r.status === key);
            const amount = matched.reduce((sum, r) => sum + (isBuy ? r.total : (r.excess_value || 0)), 0);
            return { key, label, color, count: matched.length, amount };
        });
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
        return this.sortRows(this.byStatus(this.baseFilter(this.purchaseRows)), "buy");
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
        // Los estados de una pestaña no existen en la otra
        const keys = STATUSES[this.state.tab].map(([key]) => key);
        this.state.status = this.state.status.filter((s) => keys.includes(s));
        this.draft.status = this.draft.status.filter((s) => keys.includes(s));
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

    // Tocar una tarjeta filtra sólo por ese estado; tocarla de nuevo lo quita
    onStatusCardClick(ev) {
        const { status } = ev.currentTarget.dataset;
        const only = this.state.status.length === 1 && this.state.status[0] === status;
        this.state.status = only ? [] : [status];
        this.draft.status = [...this.state.status];
        this.onCategoryChange();
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
            company: JSON.stringify(this.state.company),
            period: this.state.period,
            vendor: JSON.stringify(this.state.vendor),
            cover: this.state.buyCover,
            category: JSON.stringify(this.state.category),
            status: JSON.stringify(this.state.status),
            product: JSON.stringify(this.state.product),
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
        Object.assign(this.state, this.pickFilters(this.draft), { showFilters: false, openFilter: null });
        this.onCategoryChange();
        await this.refreshData();
    }

    async clearFilters() {
        Object.assign(this.draft, { company: [], period: "90", product: [], category: [], vendor: [], status: [] });
        this.state.filterSearch = { company: "", category: "", vendor: "", status: "", product: "" };
        await this.applyFilters();
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
                company: JSON.stringify(this.state.company),
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
                company: JSON.stringify(this.state.company),
                period: parseInt(this.state.period) || 90,
            });
            Object.assign(this.metricsData, metrics);
            Object.assign(this.state, { overPage: 1, restPage: 1 });
            // Se descartan categorías y proveedores que ya no aparecen con la nueva empresa o período
            for (const [field, options] of [["category", this.categories], ["vendor", this.vendors], ["product", this.products]]) {
                this.state[field] = this.state[field].filter((v) => options.includes(v));
                this.draft[field] = this.draft[field].filter((v) => options.includes(v));
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
