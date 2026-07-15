/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

class PriceChangeDashboard extends Component {
    static template = "product_price_change_metrics.Dashboard";

    setup() {
        this.action = useService("action");
        this.state = useState({
            company: "all",
            stateFilter: "pending",
            window: "30",
            category: "all",
            search: "",
            page: 1,
            perPage: 20,
            loading: false,
        });
        this.filters = useState({ companies: [], categories: [], current_company: null });
        this.data = useState({ rows: [], page: 1, pages: 1, total: 0, pending: 0 });
        this.selection = useState({ ids: [] });

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
                company: this.state.company,
                state: this.state.stateFilter,
                window: this.state.window,
                category: this.state.category,
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
