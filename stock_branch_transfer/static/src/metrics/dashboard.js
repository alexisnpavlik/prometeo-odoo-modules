/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useExternalListener, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

const PAGE_SIZE = 25;
const DEFAULT_PERIOD = "30";
const PERIOD_PRESETS = ["7", "30", "90", "180", "365"];
// Estados: valor (el del modelo), etiqueta y color de la tarjeta
const STATUSES = [
    ["draft", "Borrador", "purple"],
    ["in_transit", "En camino", "amber"],
    ["with_diff", "Con diferencias", "red"],
    ["received", "Recibido", "green"],
    ["closed", "Cerrado", "blue"],
];
const TABS = [
    ["pending", "Pendientes"],
    ["routes", "Rutas"],
    ["diffs", "Diferencias"],
    ["products", "Productos"],
];
const EMPTY_SEARCH = { company: "", status: "", route: "", category: "", product: "" };
const EMPTY_FILTERS = { company: [], period: DEFAULT_PERIOD, status: [], route: [], category: [], product: [] };

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

class BranchTransferMetricsDashboard extends Component {
    static template = "stock_branch_transfer.MetricsDashboard";

    setup() {
        this.action = useService("action");
        this.periodPresets = PERIOD_PRESETS;
        this.tabs = TABS;
        this.state = useState({
            ...this.pickFilters(EMPTY_FILTERS),
            openFilter: null,
            filterSearch: { ...EMPTY_SEARCH },
            tab: "pending",
            page: 1,
            // Orden elegido por pestaña: { key, dir } o null para el orden del servidor
            sort: { pending: null, routes: null, diffs: null, products: null },
            showFilters: false,
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
        });
        // Lo que se edita en la barra lateral: pasa a state recién con "Aplicar"
        this.draft = useState(this.pickFilters(EMPTY_FILTERS));
        this.filtersData = useState({ companies: [] });
        this.data = useState({
            cards: [], totals: {}, options: { routes: [], categories: [], products: [] },
            pending: [], routes: [], diffs: [], products: [],
        });

        useExternalListener(window, "click", () => {
            this.state.openFilter = null;
        });

        onWillStart(async () => {
            await this.loadFiltersMetadata();
            await this.refreshData();
        });
    }

    // Copia de los filtros: las listas se duplican para que el borrador no edite el estado aplicado
    pickFilters({ company, period, status, route, category, product }) {
        return {
            company: [...company], period, status: [...status],
            route: [...route], category: [...category], product: [...product],
        };
    }

    // --- Tarjetas y tablas ---
    get statusCards() {
        return STATUSES.map(([key, label, color]) => {
            const card = this.data.cards.find((c) => c.key === key) || { count: 0, cost: 0 };
            return { key, label, color, count: card.count, cost: card.cost };
        });
    }

    statusLabel(key) {
        const found = STATUSES.find(([value]) => value === key);
        return found ? found[1] : key;
    }

    tableRows(tab) {
        const rows = this.data[tab] || [];
        const sort = this.state.sort[tab];
        return sort ? [...rows].sort(compareBy(sort.key, sort.dir)) : rows;
    }

    pageData(tab) {
        const rows = this.tableRows(tab);
        const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
        const current = Math.min(this.state.page, pages);
        return { rows: rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE), current, pages, total: rows.length };
    }

    get pendingLate() {
        return this.data.pending.filter((r) => r.late).length;
    }

    get diffTotals() {
        let missing = 0;
        let extra = 0;
        for (const r of this.data.diffs) {
            if (r.diff < 0) missing += -r.diff_cost;
            else extra += r.diff_cost;
        }
        return { missing, extra };
    }

    // --- Multi-selección ---
    filterOptions(field) {
        if (field === "company") return this.filtersData.companies.map((c) => [c, c]);
        if (field === "status") return STATUSES.map(([key, label]) => [key, label]);
        const source = { route: "routes", category: "categories", product: "products" }[field];
        return this.data.options[source].map((v) => [v, v]);
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
    }

    selectAllFilterValues(field) {
        this.draft[field] = [];
    }

    onFilterSearchInput(field, ev) {
        this.state.filterSearch[field] = ev.target.value;
    }

    // --- Eventos ---
    onPresetClick(ev) {
        this.draft.period = ev.currentTarget.dataset.period;
    }

    onTabClick(ev) {
        this.state.tab = ev.currentTarget.dataset.tab;
        this.state.page = 1;
    }

    // Tocar una tarjeta filtra sólo por ese estado; tocarla de nuevo lo quita. Se aplica al instante.
    async onStatusCardClick(ev) {
        const { status } = ev.currentTarget.dataset;
        const only = this.state.status.length === 1 && this.state.status[0] === status;
        this.state.status = only ? [] : [status];
        this.draft.status = [...this.state.status];
        this.state.page = 1;
        await this.refreshData();
    }

    // Cada click en el encabezado: ascendente → descendente → orden por defecto
    onSortClick(ev) {
        const { key } = ev.currentTarget.dataset;
        const tab = this.state.tab;
        const sort = this.state.sort[tab];
        if (!sort || sort.key !== key) {
            this.state.sort[tab] = { key, dir: "asc" };
        } else if (sort.dir === "asc") {
            this.state.sort[tab] = { key, dir: "desc" };
        } else {
            this.state.sort[tab] = null;
        }
        this.state.page = 1;
    }

    sortMark(key) {
        const sort = this.state.sort[this.state.tab];
        if (!sort || sort.key !== key) return "";
        return sort.dir === "asc" ? "▲" : "▼";
    }

    changePage(ev) {
        this.state.page = Math.max(1, this.state.page + parseInt(ev.currentTarget.dataset.dir));
    }

    openTransfer(ev) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.branch.transfer",
            res_id: parseInt(ev.currentTarget.dataset.id),
            views: [[false, "form"]],
            target: "current",
        });
    }

    toggleFilters() {
        this.state.showFilters = !this.state.showFilters;
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
    }

    async applyFilters() {
        Object.assign(this.state, this.pickFilters(this.draft), { showFilters: false, openFilter: null, page: 1 });
        await this.refreshData();
    }

    async clearFilters() {
        Object.assign(this.draft, this.pickFilters(EMPTY_FILTERS));
        this.state.filterSearch = { ...EMPTY_SEARCH };
        await this.applyFilters();
    }

    // Listas en JSON: separadas por comas romperían los nombres que ya tienen comas
    filterParams() {
        const { company, period, status, route, category, product } = this.state;
        return {
            company: JSON.stringify(company),
            period,
            status: JSON.stringify(status),
            route: JSON.stringify(route),
            category: JSON.stringify(category),
            product: JSON.stringify(product),
        };
    }

    exportExcel() {
        const params = new URLSearchParams(this.filterParams());
        window.open(`/stock_branch_transfer/metrics/export?${params.toString()}`, "_blank");
    }

    // --- Formateadores ---
    formatCurrency(val) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency", currency: "ARS", maximumFractionDigits: 0,
        }).format(val || 0);
    }

    formatNumber(val) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(val || 0);
    }

    // Horas → "5 h" o "2,5 días"
    formatHours(val) {
        if (val === null || val === undefined) return "—";
        return val < 48 ? `${this.formatNumber(val)} h` : `${this.formatNumber(val / 24)} días`;
    }

    // --- RPC ---
    async loadFiltersMetadata() {
        try {
            Object.assign(this.filtersData, await rpc("/stock_branch_transfer/metrics/filters", {}));
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const data = await rpc("/stock_branch_transfer/metrics/data", this.filterParams());
            Object.assign(this.data, data);
            // Se descartan opciones elegidas que ya no aparecen con la nueva empresa o período
            for (const [field, source] of [["route", "routes"], ["category", "categories"], ["product", "products"]]) {
                const options = data.options[source];
                this.state[field] = this.state[field].filter((v) => options.includes(v));
                this.draft[field] = this.draft[field].filter((v) => options.includes(v));
            }
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar métricas de Traslados:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("actions").add("stock_branch_transfer.metrics_dashboard", BranchTransferMetricsDashboard);
