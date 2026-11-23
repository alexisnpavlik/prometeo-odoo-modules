/** @odoo-module **/
import { registry } from "@web/core/registry";

/**
 * Empresas activas según la cookie `cids`.
 */
function activeCompanyIds() {
    const part = document.cookie.split("; ").find((p) => p.startsWith("cids="));
    return part ? part.slice(5).split("-").map(Number) : [];
}

/**
 * Último paso de cada tour: espera unos segundos y confirma que la página no
 * se volvió a recargar (si hubiera un bucle, la marca se pierde).
 */
function noReloadLoop() {
    return [
        {
            content: "marca la página actual",
            trigger: "body",
            run() {
                window.__scs_marker = true;
            },
        },
        {
            content: "la página no se recarga sola",
            trigger: "body",
            async run() {
                await new Promise((resolve) => setTimeout(resolve, 4000));
                if (!window.__scs_marker) {
                    throw new Error("La página se recargó sola: bucle de cambio de empresa");
                }
            },
        },
    ];
}

/**
 * Tour con los datos que arma el test en Python: cada paso de verificación
 * compara la cookie `cids` con lo que espera ese escenario.
 */
function checkCompanies(content, check) {
    return {
        content,
        trigger: "body",
        run() {
            const ids = activeCompanyIds();
            const error = check(ids);
            if (error) {
                throw new Error(`${content}: ${error} (cids=${ids.join("-")})`);
            }
        },
    };
}

// Registro de otra empresa: entra a esa empresa, sola.
registry.category("web_tour.tours").add("scs_record_other_company", {
    steps: () => [
        {
            content: "el formulario del contacto de la otra empresa carga",
            trigger: ".o_form_view .o_breadcrumb .active:contains(SCS Solo B)",
        },
        checkCompanies("una sola empresa activa", (ids) =>
            ids.length === 1 ? null : "esperaba una sola empresa"
        ),
        ...noReloadLoop(),
    ],
});

// Selector: tocar el casillero de otra empresa deja solo esa.
registry.category("web_tour.tours").add("scs_switcher_single", {
    steps: () => [
        {
            content: "abre el selector de empresas",
            trigger: ".o_switch_company_menu button",
            run: "click",
        },
        {
            content: "toca el casillero de la empresa B",
            trigger: ".o_switch_company_item:contains(SCS Empresa B) [role=menuitemradio]",
            run: "click",
            expectUnloadPage: true,
        },
        {
            content: "la barra muestra la empresa B",
            trigger: ".o_switch_company_menu button:contains(SCS Empresa B)",
        },
        checkCompanies("solo la empresa B", (ids) =>
            ids.length === 1 ? null : "esperaba una sola empresa"
        ),
        ...noReloadLoop(),
    ],
});

// Ajustes con empleados de dos empresas (caso prod): carga o muestra el error,
// pero nunca queda recargando.
registry.category("web_tour.tours").add("scs_settings_no_loop", {
    steps: () => [
        {
            content: "Ajustes cargó o se mostró un error",
            trigger: ".o_form_view .o_setting_box, .o_form_view .o_setting_container, .o_form_view .app_settings_block, .modal-dialog .modal-body",
            run() {
                const loaded = Boolean(document.querySelector(".o_form_view .app_settings_block, .o_form_view .o_setting_box"));
                console.log(`SCS_RESULT settings_loaded=${loaded} cids=${activeCompanyIds().join("-")}`);
            },
        },
        ...noReloadLoop(),
        {
            content: "Ajustes cargó",
            trigger: ".o_form_view .app_settings_block, .o_form_view .o_setting_box",
        },
    ],
});

// Usuario sin la otra empresa: Odoo no puede mostrar Ajustes; error a la vista, sin bucle.
registry.category("web_tour.tours").add("scs_settings_error_no_loop", {
    steps: () => [
        {
            content: "aparece el error de acceso",
            trigger: ".modal-dialog .modal-body",
        },
        checkCompanies("sigue con una sola empresa", (ids) =>
            ids.length === 1 ? null : "esperaba una sola empresa"
        ),
        ...noReloadLoop(),
    ],
});
