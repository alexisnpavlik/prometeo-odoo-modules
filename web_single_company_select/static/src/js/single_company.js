/** @odoo-module **/
import { cookie } from "@web/core/browser/cookie";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";
import { companyService } from "@web/webclient/company_service";
import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";

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

patch(companyService, {
    /**
     * Envuelve el servicio original para que siempre haya una sola empresa activa.
     */
    start(env, deps) {
        const service = super.start(env, deps);
        const activeId = service.activeCompanyIds[0];
        if (service.activeCompanyIds.length > 1) {
            cookie.set("cids", String(activeId));
            user.updateContext({ allowed_company_ids: [activeId] });
        }
        return Object.create(service, {
            activeCompanyIds: {
                get: () => [activeId],
            },
            currentCompany: {
                get: () => service.allowedCompanies[activeId],
            },
            setCompanies: {
                value: (companyIds) => {
                    const targetId = pickSingleCompanyId(companyIds || [], [activeId]);
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
