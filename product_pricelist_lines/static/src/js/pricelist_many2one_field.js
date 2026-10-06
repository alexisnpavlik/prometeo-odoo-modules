/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Many2OneField, many2OneField } from "@web/views/fields/many2one/many2one_field";

// El many2one estándar muestra 7 opciones y el resto queda detrás de
// "Buscar más..."; con una lista por sucursal más las mayoristas eso esconde
// listas. Odoo 18 no expone searchLimit como option de la vista.
// "Buscar más..." se apaga: su diálogo pierde el allowed_company_ids del campo
// y sólo busca en la empresa tildada (con Depósito queda vacío).
const SEARCH_LIMIT = 50;

export class PricelistMany2OneField extends Many2OneField {
    get Many2XAutocompleteProps() {
        return {
            ...super.Many2XAutocompleteProps,
            searchLimit: SEARCH_LIMIT,
            noSearchMore: true,
        };
    }
}

registry.category("fields").add("pricelist_many2one_all", {
    ...many2OneField,
    component: PricelistMany2OneField,
});
