/** @odoo-module **/
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { companyService } from "@web/webclient/company_service";
import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";

const LAST_AUTO_SWITCH_KEY = "web_single_company_select.last_auto_switch";
const MULTI_IDS_KEY = "web_single_company_select.multi_ids";
const AUTO_COUNT_KEY = "web_single_company_select.auto_count";
const BOUNCE_WINDOW_MS = 60000;
const MAX_AUTO_SWITCHES = 2;

/**
 * Corta el cambio automático de empresa: en lugar de recargar la página se
 * muestra el error original del formulario. Nunca puede haber un bucle.
 */
function stopAutoSwitch() {
    writeSession(AUTO_COUNT_KEY, null);
    writeSession(LAST_AUTO_SWITCH_KEY, null);
    throw new Error(
        "web_single_company_select: no se cambió de empresa automáticamente para no entrar en un bucle de recargas. Elegí la empresa en el selector."
    );
}

/**
 * Suma un cambio automático a la ventana actual y dice si se pasó del máximo.
 */
function autoSwitchLimitReached(now) {
    const count = readSession(AUTO_COUNT_KEY);
    const recent = count && now - count.ts < BOUNCE_WINDOW_MS ? count : { n: 0, ts: now };
    if (recent.n >= MAX_AUTO_SWITCHES) {
        return true;
    }
    writeSession(AUTO_COUNT_KEY, { n: recent.n + 1, ts: recent.ts });
    return false;
}

/**
 * Lee un valor JSON de sessionStorage sin romper si no está disponible.
 */
function readSession(key) {
    try {
        return JSON.parse(browser.sessionStorage.getItem(key) || "null");
    } catch {
        return null;
    }
}

/**
 * Guarda (o borra, con null) un valor JSON en sessionStorage.
 */
function writeSession(key, value) {
    try {
        if (value === null) {
            browser.sessionStorage.removeItem(key);
        } else {
            browser.sessionStorage.setItem(key, JSON.stringify(value));
        }
    } catch {
        // sin sessionStorage: se pierde la protección anti-rebote, nada más
    }
}

/**
 * Compara dos listas de ids como conjuntos.
 */
function sameIds(a, b) {
    return a.length === b.length && a.every((id) => b.includes(id));
}

/**
 * Elige la única empresa que queda activa a partir de un pedido de cambio.
 *
 * Gana la primera empresa pedida que todavía no estaba activa: así funciona
 * tanto el selector (pone la elegida adelante) como el cambio automático del
 * formulario (agrega la empresa del registro al final). Si no hay ninguna
 * nueva, se queda la primera pedida; si el pedido viene vacío, la actual.
 *
 * @param {number[]} requestedIds empresas pedidas
 * @param {number[]} activeIds empresas activas hoy
 * @returns {number}
 */
export function pickSingleCompanyId(requestedIds, activeIds) {
    const added = requestedIds.find((id) => !activeIds.includes(id));
    return added ?? requestedIds[0] ?? activeIds[0];
}

/**
 * ¿Es un rebote? El formulario pide volver a la empresa de la que se acaba de
 * salir por un cambio automático: la pantalla necesita las dos a la vez (p. ej.
 * Ajustes muestra empleados de varias empresas) y saltar entre ellas sería un
 * bucle de recargas.
 *
 * @param {{from: number, to: number, ts: number}|null} lastAutoSwitch
 * @param {number} currentId empresa activa hoy
 * @param {number} targetId empresa que pide el formulario
 * @param {number} now
 * @returns {boolean}
 */
export function isBounce(lastAutoSwitch, currentId, targetId, now) {
    return Boolean(
        lastAutoSwitch &&
            now - lastAutoSwitch.ts < BOUNCE_WINDOW_MS &&
            lastAutoSwitch.to === currentId &&
            lastAutoSwitch.from === targetId
    );
}

patch(companyService, {
    /**
     * Envuelve el servicio original para que haya una sola empresa activa.
     *
     * Única excepción: una pantalla que necesita registros de varias empresas
     * a la vez (detectada por rebote). Ahí se dejan activas las que pide,
     * hasta que el usuario elija una empresa en el selector.
     */
    start(env, deps) {
        const service = super.start(env, deps);
        const multiIds = readSession(MULTI_IDS_KEY);
        let activeIds = service.activeCompanyIds;
        if (activeIds.length > 1 && !(multiIds && sameIds(multiIds, activeIds))) {
            activeIds = [activeIds[0]];
            cookie.set("cids", String(activeIds[0]));
            user.updateContext({ allowed_company_ids: activeIds });
            writeSession(MULTI_IDS_KEY, null);
        }
        const multiMode = activeIds.length > 1;

        return Object.create(service, {
            activeCompanyIds: {
                get: () => activeIds.slice(),
            },
            currentCompany: {
                get: () => service.allowedCompanies[activeIds[0]],
            },
            setCompanies: {
                value: (companyIds) => {
                    const requested = companyIds || [];
                    // el formulario agrega la empresa del registro a las activas;
                    // el selector siempre pide una sola empresa
                    const isAutoAdd =
                        requested.length > activeIds.length &&
                        activeIds.every((id) => requested.includes(id));
                    if (!isAutoAdd) {
                        writeSession(MULTI_IDS_KEY, null);
                        writeSession(LAST_AUTO_SWITCH_KEY, null);
                        writeSession(AUTO_COUNT_KEY, null);
                        const targetId = pickSingleCompanyId(requested, activeIds);
                        return service.setCompanies([targetId], false);
                    }
                    const targetId = pickSingleCompanyId(requested, activeIds);
                    // la empresa pedida ya está activa: recargar no arregla nada
                    if (activeIds.includes(targetId)) {
                        return stopAutoSwitch();
                    }
                    if (autoSwitchLimitReached(Date.now())) {
                        return stopAutoSwitch();
                    }
                    const lastAutoSwitch = readSession(LAST_AUTO_SWITCH_KEY);
                    if (
                        multiMode ||
                        isBounce(lastAutoSwitch, activeIds[0], targetId, Date.now())
                    ) {
                        const ids = [...new Set([...activeIds, targetId])];
                        writeSession(MULTI_IDS_KEY, ids);
                        writeSession(LAST_AUTO_SWITCH_KEY, null);
                        return service.setCompanies(ids, false);
                    }
                    writeSession(LAST_AUTO_SWITCH_KEY, {
                        from: activeIds[0],
                        to: targetId,
                        ts: Date.now(),
                    });
                    return service.setCompanies([targetId], false);
                },
            },
        });
    },
});

patch(CompanySelector.prototype, {
    /**
     * Casillero o nombre: en los dos casos se entra a esa empresa sola.
     */
    switchCompany(mode, companyId) {
        if (!(companyId in this.companyService.allowedCompanies)) {
            return;
        }
        this.selectedCompaniesIds.splice(0, this.selectedCompaniesIds.length, companyId);
        if (this.hasSelectionChanged) {
            this.apply();
        }
        this.dropdownState.close?.();
    },

    /**
     * "Seleccionar todas" no tiene sentido con una sola empresa activa.
     */
    selectAll() {},
});
