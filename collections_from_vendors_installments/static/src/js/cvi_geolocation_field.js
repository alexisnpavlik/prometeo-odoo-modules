/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

// Motivos de fallo de la Geolocation API. El navegador solo da un código numérico.
const GEO_ERRORS = {
    1: _t("Permiso denegado. Habilitá la ubicación para este sitio en el navegador."),
    2: _t("No se pudo determinar la posición. Probá al aire libre o con datos activos."),
    3: _t("El GPS tardó demasiado en responder. Volvé a intentar."),
};

export class CviGeolocationField extends Component {
    static template = "collections_from_vendors_installments.CviGeolocationField";
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
        this.state = useState({ busy: false });
    }

    get latitude() {
        return this.props.record.data.cvi_latitude;
    }

    get longitude() {
        return this.props.record.data.cvi_longitude;
    }

    get hasCoordinates() {
        return Boolean(this.latitude || this.longitude);
    }

    get coordinatesLabel() {
        if (!this.hasCoordinates) {
            return "";
        }
        return `${this.latitude.toFixed(6)}, ${this.longitude.toFixed(6)}`;
    }

    get accuracyLabel() {
        const accuracy = this.props.record.data.cvi_geo_accuracy;
        return accuracy ? _t("±%s m", Math.round(accuracy)) : "";
    }

    async capture() {
        // La Geolocation API solo existe en contexto seguro: https, o localhost. Servido
        // por http a una IP de la red local el navegador ni siquiera la expone, y el
        // vendedor vería un botón que no hace nada.
        if (!navigator.geolocation) {
            this.notification.add(
                _t(
                    "Este navegador no permite tomar la ubicación. Suele pasar cuando el " +
                    "sistema no se sirve por HTTPS."
                ),
                { type: "danger" }
            );
            return;
        }
        this.state.busy = true;
        try {
            const position = await new Promise((resolve, reject) => {
                navigator.geolocation.getCurrentPosition(resolve, reject, {
                    enableHighAccuracy: true,
                    timeout: 15000,
                    maximumAge: 0,
                });
            });
            await this.props.record.update({
                cvi_latitude: position.coords.latitude,
                cvi_longitude: position.coords.longitude,
                cvi_geo_accuracy: position.coords.accuracy || 0,
            });
            this.notification.add(_t("Ubicación tomada."), { type: "success" });
        } catch (error) {
            this.notification.add(
                GEO_ERRORS[error && error.code] || _t("No se pudo tomar la ubicación."),
                { type: "danger" }
            );
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("fields").add("cvi_geolocation", {
    component: CviGeolocationField,
    supportedTypes: ["float"],
});
