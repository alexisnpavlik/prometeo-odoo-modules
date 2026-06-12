import { CompanySelector } from "@web/webclient/switch_company_menu/switch_company_menu";
import { patch } from "@web/core/utils/patch";

patch(CompanySelector.prototype, {
    switchCompany(mode, companyId) {
        if (mode === "toggle") {
            if (this.selectedCompaniesIds.includes(companyId) && this.selectedCompaniesIds.length === 1) {
                // Ya es la única empresa activa — no hacer nada
                return;
            }
            // Limpiar todas y activar solo la seleccionada
            this.selectedCompaniesIds.splice(0, this.selectedCompaniesIds.length);
            this._selectCompany(companyId);
        } else if (mode === "loginto") {
            // Siempre limpiar antes de entrar a la nueva empresa
            this.selectedCompaniesIds.splice(0, this.selectedCompaniesIds.length);
            this._selectCompany(companyId, true);
            this.apply();
            this.dropdownState?.close?.();
        } else {
            return super.switchCompany(mode, companyId);
        }
    },
});
