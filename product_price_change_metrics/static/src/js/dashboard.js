/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useExternalListener, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

class PriceChangeDashboard extends Component {
    static template = "product_price_change_metrics.Dashboard";

    setup() {
        this.action = useService("action");
        this.state = useState({
            company: [],
            stateFilter: "pending",
            window: "30",
            category: [],
            search: "",
            openFilter: null,
            filterSearch: { company: "", category: "" },
            page: 1,
            perPage: 20,
            loading: false,
        });
        this.filters = useState({ companies: [], categories: [], current_company: null });
        this.data = useState({ rows: [], page: 1, pages: 1, total: 0, pending: 0 });
        this.selection = useState({ ids: [] });

        // Click afuera cierra el desplegable abierto; adentro lo frena t-on-click.stop
        useExternalListener(window, "click", () => {
            this.state.openFilter = null;
        });

        onWillStart(async () => {
            await this.loadFilters();
            await this.refresh();
        });
    }

    async loadFilters() {
        const res = await rpc("/product_price_change_metrics/filters", {});
        this.filters.companies = res.companies;
        this.filters.categories = res.categories;
        this.filters.current_company = res.current_company;
    }

    async refresh() {
        this.state.loading = true;
        try {
            const res = await rpc("/product_price_change_metrics/changes", {
                company: [...this.state.company],
                state: this.state.stateFilter,
                window: this.state.window,
                category: [...this.state.category],
                search: this.state.search,
                page: this.state.page,
                per_page: this.state.perPage,
            });
            this.data.rows = res.rows;
            this.data.page = res.page;
            this.data.pages = res.pages;
            this.data.total = res.total;
            this.data.pending = res.pending;
            this.selection.ids = [];
        } finally {
            this.state.loading = false;
        }
    }

    onFilterChange() {
        this.state.page = 1;
        this.refresh();
    }

    // --- Filtros multi-selección (mismo patrón que métricas gerenciales) ---
    // Como el resto de los filtros de esta pantalla, cada tilde aplica al instante.
    filterOptions(field) {
        if (field === "company") return this.filters.companies.map((c) => [c.id, c.name]);
        if (field === "category") return this.filters.categories.map((c) => [c.id, c.name]);
        return [];
    }

    visibleOptions(field) {
        const term = this.state.filterSearch[field].toLowerCase().trim();
        const options = this.filterOptions(field);
        return term ? options.filter(([, label]) => String(label).toLowerCase().includes(term)) : options;
    }

    multiLabel(field, emptyLabel, pluralLabel) {
        const selection = this.state[field];
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
        return this.state[field].includes(value);
    }

    toggleFilterValue(field, value) {
        const selection = this.state[field];
        const idx = selection.indexOf(value);
        if (idx === -1) {
            selection.push(value);
        } else {
            selection.splice(idx, 1);
        }
        this.onFilterChange();
    }

    selectAllFilterValues(field) {
        this.state[field] = [];
        this.onFilterChange();
    }

    onFilterSearchInput(field, ev) {
        this.state.filterSearch[field] = ev.target.value;
    }

    goToPage(p) {
        if (p < 1 || p > this.data.pages) {
            return;
        }
        this.state.page = p;
        this.refresh();
    }

    toggleRow(id) {
        const idx = this.selection.ids.indexOf(id);
        if (idx >= 0) {
            this.selection.ids.splice(idx, 1);
        } else {
            this.selection.ids.push(id);
        }
    }

    isSelected(id) {
        return this.selection.ids.includes(id);
    }

    async markDone(done) {
        if (!this.selection.ids.length) {
            return;
        }
        await rpc("/product_price_change_metrics/mark_done", {
            ids: this.selection.ids,
            done: done,
        });
        await this.refresh();
    }

    openProduct(tmplId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.template",
            res_id: tmplId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("product_price_change_metrics.dashboard", PriceChangeDashboard);
