/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onMounted, onWillStart, onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";

const PAGE_SIZE = 25;
const PERIOD_PRESETS = [
    ["today", "Hoy"],
    ["yesterday", "Ayer"],
    ["7days", "Últimos 7 días"],
    ["30days", "Últimos 30 días"],
    ["month", "Este mes"],
];
// Estado de cada sesión de caja: valor (lo decide el controlador), etiqueta y color de la tarjeta
const STATUSES = [
    ["abierta_hoy", "Abierta hoy", "green"],
    ["abierta_vieja", "Abierta hace días", "amber"],
    ["cerro_justo", "Cerró justo", "blue"],
    ["faltante", "Cerró con faltante", "red"],
    ["sobrante", "Cerró con sobrante", "purple"],
];
const EMPTY_SEARCH = { company: "", pos: "", status: "", cashier: "" };
const TABLES = ["cashiers", "sessions", "moves"];

// Fecha local YYYY-MM-DD: toISOString() la pasaría a UTC y a la noche daría el día siguiente
const fmtDate = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// Desde/hasta de un preset. Los extremos son inclusivos: "últimos 7 días" es hoy y los 6 anteriores
const presetRange = (preset) => {
    const today = new Date();
    const start = new Date(today);
    const end = new Date(today);
    if (preset === "yesterday") {
        start.setDate(today.getDate() - 1);
        end.setDate(today.getDate() - 1);
    } else if (preset === "7days") {
        start.setDate(today.getDate() - 6);
    } else if (preset === "30days") {
        start.setDate(today.getDate() - 29);
    } else if (preset === "month") {
        start.setDate(1);
    }
    return { startDate: fmtDate(start), endDate: fmtDate(end) };
};

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

const EMPTY_DATA = {
    range: { start: "", end: "", today: "" },
    kpis: {
        sold: 0, tickets: 0, avg_ticket: 0, refunds: 0, cash_now: 0, open_today: 0, cash_old: 0, open_old: 0,
        withdrawals: 0, withdrawals_count: 0, deposits: 0, deposits_count: 0, difference: 0, shortage: 0,
        closed: 0, closed_with_diff: 0,
    },
    cashiers: [],
    sessions: [],
    moves: [],
    methods: [],
};
const TOP_CASHIERS = 10;
// Mismos colores que los gráficos de métricas gerenciales (pos_management_metrics)
const CHART_FILLS = [
    "rgba(16, 185, 129, 0.65)", "rgba(59, 130, 246, 0.65)", "rgba(139, 92, 246, 0.65)",
    "rgba(245, 158, 11, 0.65)", "rgba(239, 68, 68, 0.65)", "rgba(6, 182, 212, 0.65)",
    "rgba(236, 72, 153, 0.65)", "rgba(107, 114, 128, 0.65)", "rgba(168, 85, 247, 0.65)",
];
const CHART_BORDERS = ["#10b981", "#3b82f6", "#8b5cf6", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#6b7280", "#a855f7"];

class PosCashMetricsDashboard extends Component {
    static template = "pos_cash_metrics.DashboardTemplate";

    setup() {
        this.periodPresets = PERIOD_PRESETS;
        this.state = useState({
            // Filtros aplicados. Multi-selección: lista vacía = "todos"
            preset: "today",
            ...presetRange("today"),
            company: [],
            pos: [],
            status: [],
            cashier: [],
            // Tarjetas de la pestaña de retiros: null, "retiro" o "ingreso"
            moveKind: null,
            openFilter: null,
            filterSearch: { ...EMPTY_SEARCH },
            tab: "resumen",
            page: { cashiers: 1, sessions: 1, moves: 1 },
            sort: { cashiers: null, sessions: null, moves: null },
            showFilters: false,
            loading: false,
            syncTime: "Cargando...",
            theme: "dark",
        });

        // Lo que se edita en la barra lateral: pasa a state recién con "Aplicar", como en los demás dashboards
        this.draft = useState(this.pickFilters(this.state));

        this.filtersData = useState({ companies: [], configs: [], cashiers: [] });
        // Transacciones: paginadas en el servidor (un mes son decenas de miles de líneas)
        this.tx = useState({ rows: [], total: 0, page: 1, pages: 1, search: "", loading: false, loaded: false });
        this.data = useState(structuredClone(EMPTY_DATA));

        // Cierra el panel de checkboxes al hacer clic fuera del filtro
        useExternalListener(window, "click", () => {
            this.state.openFilter = null;
        });

        this.charts = {};

        onWillStart(async () => {
            // Chart.js v4 que sirve el propio Odoo; sin él el dashboard abre igual, sin gráficos
            try {
                await loadBundle("web.chartjs_lib");
            } catch (e) {
                console.warn("Chart.js no disponible", e);
            }
            await this.loadFiltersMetadata();
            await this.refreshData();
        });

        onMounted(() => {
            this.isMounted = true;
            this.renderCharts();
        });

        onWillUnmount(() => {
            Object.values(this.charts).forEach((chart) => chart && chart.destroy());
        });
    }

    // Copia de los filtros: las listas se duplican para que el borrador no edite el estado aplicado
    pickFilters({ preset, startDate, endDate, company, pos, status, cashier }) {
        return {
            preset, startDate, endDate,
            company: [...company], pos: [...pos], status: [...status], cashier: [...cashier],
        };
    }

    // --- Resumen ---
    get kpis() {
        return this.data.kpis;
    }

    get chartCashiers() {
        return this.data.cashiers.filter((c) => c.sold > 0).slice(0, TOP_CASHIERS);
    }

    get moreCashiers() {
        return Math.max(0, this.data.cashiers.filter((c) => c.sold > 0).length - TOP_CASHIERS);
    }

    get chartMethods() {
        return this.data.methods.filter((m) => m.amount > 0);
    }

    goToCashiers() {
        this.state.tab = "cajeros";
    }

    get openSessions() {
        return this.data.sessions.filter((s) => s.is_open).sort((a, b) => a.days_open - b.days_open);
    }

    get rangeLabel() {
        const { start, end } = this.data.range;
        const nice = (d) => (d ? d.split("-").reverse().join("/") : "");
        return start === end ? nice(start) : `${nice(start)} al ${nice(end)}`;
    }

    // --- Cajeros ---
    bestBy(key) {
        const rows = this.data.cashiers.filter((c) => c[key] > 0);
        return rows.length ? rows.reduce((best, c) => (c[key] > best[key] ? c : best)) : null;
    }

    get cashierCards() {
        return [
            { key: "sold", label: "Más vendió", color: "green", row: this.bestBy("sold"), value: (r) => this.formatCurrency(r.sold), sub: (r) => `${this.formatNumber(r.tickets)} tickets` },
            { key: "tickets", label: "Más tickets", color: "blue", row: this.bestBy("tickets"), value: (r) => this.formatNumber(r.tickets), sub: (r) => `promedio ${this.formatCurrency(r.avg_ticket)}` },
            { key: "shortage", label: "Mayor faltante", color: "red", row: this.bestBy("shortage"), value: (r) => `− ${this.formatCurrency(r.shortage)}`, sub: (r) => `${r.shortages} cierres con faltante` },
            { key: "withdrawals", label: "Más retiró", color: "amber", row: this.bestBy("withdrawals"), value: (r) => this.formatCurrency(r.withdrawals), sub: (r) => `${r.withdrawals_count} retiros` },
        ];
    }

    get cashierRows() {
        return this.sortRows(this.data.cashiers, "cashiers");
    }

    // --- Cajas y cierres ---
    get filteredSessions() {
        const { status } = this.state;
        const rows = status.length ? this.data.sessions.filter((s) => status.includes(s.status)) : this.data.sessions;
        return this.sortRows(rows, "sessions");
    }

    // Tarjetas por estado: cuentan sobre todas las sesiones, sin el filtro de estado
    get statusCards() {
        return STATUSES.map(([key, label, color]) => {
            const rows = this.data.sessions.filter((s) => s.status === key);
            let sub = `${rows.length === 1 ? "1 caja" : `${rows.length} cajas`}`;
            if (key === "abierta_hoy" || key === "abierta_vieja") {
                sub = `${this.formatCurrency(rows.reduce((t, s) => t + (s.expected || 0), 0))} en caja`;
            } else if (key === "faltante" || key === "sobrante") {
                sub = this.formatSigned(rows.reduce((t, s) => t + (s.difference || 0), 0));
            }
            return { key, label, color, count: rows.length, sub };
        });
    }

    statusLabel(key) {
        const found = STATUSES.find(([value]) => value === key);
        return found ? found[1] : key;
    }

    // --- Retiros e ingresos ---
    get moveCards() {
        const k = this.kpis;
        return [
            { key: "retiro", label: "Retiros", color: "amber", count: k.withdrawals_count, amount: k.withdrawals },
            { key: "ingreso", label: "Ingresos", color: "green", count: k.deposits_count, amount: k.deposits },
        ];
    }

    get filteredMoves() {
        const kind = this.state.moveKind;
        return this.sortRows(kind ? this.data.moves.filter((m) => m.kind === kind) : this.data.moves, "moves");
    }

    // --- Tablas ---
    sortRows(rows, table) {
        const sort = this.state.sort[table];
        return sort ? [...rows].sort(compareBy(sort.key, sort.dir)) : rows;
    }

    sortMark(table, key) {
        const sort = this.state.sort[table];
        if (!sort || sort.key !== key) return "";
        return sort.dir === "asc" ? "▲" : "▼";
    }

    pageOf(rows, table) {
        const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
        const current = Math.min(this.state.page[table], pages);
        return { rows: rows.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE), current, pages, total: rows.length };
    }

    get cashierPage() {
        return this.pageOf(this.cashierRows, "cashiers");
    }

    get sessionPage() {
        return this.pageOf(this.filteredSessions, "sessions");
    }

    get movePage() {
        return this.pageOf(this.filteredMoves, "moves");
    }

    resetPages() {
        for (const table of TABLES) {
            this.state.page[table] = 1;
        }
    }

    // --- Multi-selección ---
    // Cajas: sólo las de las empresas elegidas en el borrador
    get configOptions() {
        const { company } = this.draft;
        return this.filtersData.configs.filter((c) => !company.length || company.includes(c.company));
    }

    filterOptions(field) {
        if (field === "company") return this.filtersData.companies.map((c) => [c, c]);
        if (field === "pos") return this.configOptions.map((c) => [c.id, c.name]);
        if (field === "status") return STATUSES.map(([key, label]) => [key, label]);
        return this.filtersData.cashiers.map((c) => [c.id, c.name]);
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
            return option ? option[1] : String(selection[0]);
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
        if (field === "company") {
            this.pruneDraftConfigs();
        }
    }

    selectAllFilterValues(field) {
        this.draft[field] = [];
        if (field === "company") {
            this.pruneDraftConfigs();
        }
    }

    // Al cambiar de empresa se descartan las cajas que ya no están en la lista
    pruneDraftConfigs() {
        const ids = this.configOptions.map((c) => c.id);
        this.draft.pos = this.draft.pos.filter((id) => ids.includes(id));
    }

    onFilterSearchInput(field, ev) {
        this.state.filterSearch[field] = ev.target.value;
    }

    // --- Eventos ---
    onPresetClick(ev) {
        const preset = ev.currentTarget.dataset.preset;
        Object.assign(this.draft, { preset, ...presetRange(preset) });
    }

    onDateChange(ev) {
        this.draft[ev.currentTarget.dataset.field] = ev.target.value;
        this.draft.preset = "custom";
    }

    async onTabClick(ev) {
        this.state.tab = ev.currentTarget.dataset.tab;
        if (this.state.tab === "transacciones" && !this.tx.loaded) {
            await this.loadTransactions();
        }
    }

    // --- Transacciones ---
    async loadTransactions() {
        this.tx.loading = true;
        try {
            const data = await rpc("/pos_cash_metrics/transactions", {
                ...this.serverFilters(),
                search: this.tx.search,
                page: this.tx.page,
            });
            Object.assign(this.tx, data, { loaded: true });
        } catch (e) {
            console.error("Error al cargar transacciones:", e);
        } finally {
            this.tx.loading = false;
        }
    }

    // Búsqueda con espera de 350 ms, como en métricas gerenciales: no consultar por cada tecla
    onTxSearchInput(ev) {
        this.tx.search = ev.target.value;
        this.tx.page = 1;
        clearTimeout(this.txSearchTimeout);
        this.txSearchTimeout = setTimeout(() => this.loadTransactions(), 350);
    }

    async changeTxPage(ev) {
        const page = this.tx.page + parseInt(ev.currentTarget.dataset.dir);
        if (page < 1 || page > this.tx.pages) return;
        this.tx.page = page;
        await this.loadTransactions();
    }

    // Filtros que van al servidor, en el formato que espera el controlador
    serverFilters() {
        return {
            company: JSON.stringify(this.state.company),
            pos: JSON.stringify(this.state.pos),
            cashier: JSON.stringify(this.state.cashier),
            start_date: this.state.startDate,
            end_date: this.state.endDate,
        };
    }

    // Tocar una tarjeta filtra sólo por ese estado; tocarla de nuevo lo quita. Se aplica al instante.
    onStatusCardClick(ev) {
        const { status } = ev.currentTarget.dataset;
        const only = this.state.status.length === 1 && this.state.status[0] === status;
        this.state.status = only ? [] : [status];
        this.draft.status = [...this.state.status];
        this.state.page.sessions = 1;
    }

    onMoveCardClick(ev) {
        const { kind } = ev.currentTarget.dataset;
        this.state.moveKind = this.state.moveKind === kind ? null : kind;
        this.state.page.moves = 1;
    }

    // Desde el resumen: ir a la pestaña de cajas filtrando por ese estado
    goToSessions(ev) {
        this.state.tab = "cajas";
        const { status } = ev.currentTarget.dataset;
        if (status) {
            this.state.status = [status];
            this.draft.status = [status];
            this.state.page.sessions = 1;
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
        this.state.page[table] = 1;
    }

    changePage(ev) {
        const { table, dir } = ev.currentTarget.dataset;
        this.state.page[table] = Math.max(1, this.state.page[table] + parseInt(dir));
    }

    toggleFilters() {
        this.state.showFilters = !this.state.showFilters;
    }

    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        // Chart.js toma el color de ejes y grilla al crear el gráfico: hay que rehacerlos
        this.renderCharts();
    }

    // --- Gráficos (mismo estilo que métricas gerenciales) ---
    renderCharts() {
        if (typeof Chart === "undefined" || !this.isMounted) return;
        const isLight = this.state.theme === "light";
        const gridConfig = { color: isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.04)", drawBorder: false };
        const shorten = (l, n) => (l && l.length > n ? l.substring(0, n - 3) + "..." : l);
        const money = (v) => this.formatCurrency(v).split(",")[0];

        const cashiers = this.chartCashiers;
        this.createOrUpdateChart("pcm-chart-cashiers", "bar", {
            labels: cashiers.map((c) => shorten(c.name, 24)),
            datasets: [{
                label: "Vendido",
                data: cashiers.map((c) => c.sold),
                backgroundColor: "rgba(59, 130, 246, 0.65)",
                borderColor: "#3b82f6",
                borderWidth: 1.5,
                borderRadius: 4,
            }],
        }, {
            indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: (items) => cashiers[items[0].dataIndex].name,
                        label: (context) => {
                            const c = cashiers[context.dataIndex];
                            const lines = [` ${this.formatCurrency(c.sold)} · ${this.formatNumber(c.tickets)} tickets (promedio ${this.formatCurrency(c.avg_ticket)})`];
                            if (c.difference) {
                                lines.push(` Diferencia al cierre: ${this.formatSigned(c.difference)}`);
                            }
                            return lines;
                        },
                    },
                },
            },
            scales: {
                x: { grid: gridConfig, ticks: { callback: money } },
                y: { grid: { display: false } },
            },
        });

        const methods = this.chartMethods;
        this.createOrUpdateChart("pcm-chart-methods", "bar", {
            labels: methods.map((m) => shorten(m.group, 18)),
            datasets: [{
                label: "Participación",
                data: methods.map((m) => m.pct),
                backgroundColor: methods.map((m, i) => CHART_FILLS[i % CHART_FILLS.length]),
                borderColor: methods.map((m, i) => CHART_BORDERS[i % CHART_BORDERS.length]),
                borderWidth: 1.5,
                borderRadius: 4,
            }],
        }, {
            indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (context) => {
                            const m = methods[context.dataIndex];
                            const detail = m.details.length > 1 ? ` · ${m.details.length} métodos` : "";
                            return ` ${m.group}: ${m.pct}% (${this.formatCurrency(m.amount)})${detail}`;
                        },
                    },
                },
            },
            scales: {
                x: { grid: gridConfig, ticks: { callback: (v) => `${v}%` } },
                y: { grid: { display: false } },
            },
        });
    }

    createOrUpdateChart(canvasId, type, data, options = {}) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        // Destruir la instancia anterior evita gráficos superpuestos y hover fantasma
        if (this.charts[canvasId]) {
            this.charts[canvasId].destroy();
        }
        Chart.defaults.color = this.state.theme === "light" ? "#475569" : "#94a3b8";
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
        this.charts[canvasId] = new Chart(canvas.getContext("2d"), { type, data, options: mergedOptions });
    }

    async applyFilters() {
        // Hoy/ayer se recalculan al aplicar: un dashboard abierto desde ayer no tiene que mostrar ayer como "hoy"
        if (this.draft.preset !== "custom") {
            Object.assign(this.draft, presetRange(this.draft.preset));
        }
        Object.assign(this.state, this.pickFilters(this.draft), { showFilters: false, openFilter: null });
        this.resetPages();
        await this.refreshData();
    }

    async clearFilters() {
        Object.assign(this.draft, {
            preset: "today", ...presetRange("today"), company: [], pos: [], status: [], cashier: [],
        });
        this.state.filterSearch = { ...EMPTY_SEARCH };
        this.state.moveKind = null;
        await this.applyFilters();
    }

    exportExcel(ev) {
        // Listas en JSON: separadas por comas romperían los nombres que ya tienen comas
        const params = new URLSearchParams({
            table: ev.currentTarget.dataset.table,
            ...this.serverFilters(),
            status: JSON.stringify(this.state.status),
            search: this.tx.search,
        });
        window.open(`/pos_cash_metrics/export?${params.toString()}`, "_blank");
    }

    // --- Formateadores ---
    formatCurrency(val) {
        return new Intl.NumberFormat("es-AR", {
            style: "currency", currency: "ARS", maximumFractionDigits: 0,
        }).format(val || 0);
    }

    // Diferencias de caja con signo explícito: "− $ 17.800" / "+ $ 9.800"
    formatSigned(val) {
        if (!val || Math.abs(val) < 1) return this.formatCurrency(0);
        return `${val < 0 ? "−" : "+"} ${this.formatCurrency(Math.abs(val))}`;
    }

    signClass(val) {
        if (val === null || val === undefined || Math.abs(val) < 1) return "";
        return val < 0 ? "amount-neg" : "amount-pos";
    }

    formatNumber(val) {
        return new Intl.NumberFormat("es-AR", { maximumFractionDigits: 1 }).format(val || 0);
    }

    // --- RPC ---
    async loadFiltersMetadata() {
        try {
            Object.assign(this.filtersData, await rpc("/pos_cash_metrics/filters", {}));
        } catch (e) {
            console.error("Error al cargar metadatos de filtros:", e);
        }
    }

    async refreshData() {
        this.state.loading = true;
        this.state.syncTime = "Sincronizando...";
        try {
            const data = await rpc("/pos_cash_metrics/data", this.serverFilters());
            Object.assign(this.data, data);
            this.renderCharts();
            // Las transacciones dependen de los mismos filtros: se recargan si están a la vista
            this.tx.page = 1;
            this.tx.loaded = false;
            if (this.state.tab === "transacciones") {
                await this.loadTransactions();
            }
            this.state.syncTime = `Sincronizado: ${new Date().toLocaleTimeString()}`;
        } catch (e) {
            console.error("Error al sincronizar Métricas de Caja:", e);
            this.state.syncTime = "Error de sincronización";
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("actions").add("pos_cash_metrics.dashboard", PosCashMetricsDashboard);
