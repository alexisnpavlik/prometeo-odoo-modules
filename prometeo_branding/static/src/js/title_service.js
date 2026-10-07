/** @odoo-module **/
import { titleService } from "@web/core/browser/title_service";
import { patch } from "@web/core/utils/patch";

const BRAND_NAME = "Prometeo ERP";

// Copia del servicio base: el nombre de respaldo ("Odoo") está dentro de una
// clausura y no se puede cambiar sin reescribir start().
patch(titleService, {
    start() {
        const titleCounters = {};
        const titleParts = {};

        function updateTitle() {
            const counter = Object.values(titleCounters).reduce((acc, count) => acc + count, 0);
            const name = Object.values(titleParts).join(" - ") || BRAND_NAME;
            document.title = counter ? `(${counter}) ${name}` : name;
        }

        function assign(target, values) {
            for (const key in values) {
                if (!values[key]) {
                    delete target[key];
                } else {
                    target[key] = values[key];
                }
            }
            updateTitle();
        }

        return {
            get current() {
                return document.title;
            },
            getParts: () => Object.assign({}, titleParts),
            setCounters: (counters) => assign(titleCounters, counters),
            setParts: (parts) => assign(titleParts, parts),
        };
    },
});
