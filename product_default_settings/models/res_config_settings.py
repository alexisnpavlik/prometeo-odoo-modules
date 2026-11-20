from odoo import api, fields, models

PARAM_PREFIX = "product_default_settings."

# Ajuste -> valor por defecto. Son globales (ir.config_parameter): aplican a
# todos los usuarios por igual, sin grupos.
PRODUCT_FORM_SETTINGS = {
    "edit_defaults": False,
    "show_page_variants": False,
    "show_page_sales": False,
    "show_page_purchase": False,
    "show_page_inventory": False,
    "show_page_pos": True,
}


def get_product_form_settings(env):
    """Devuelve {ajuste: bool} leyendo los parámetros del sistema.

    Si el parámetro no existe se usa el default de PRODUCT_FORM_SETTINGS.
    """
    icp = env["ir.config_parameter"].sudo()
    return {
        key: icp.get_param(PARAM_PREFIX + key, str(default)) == "True"
        for key, default in PRODUCT_FORM_SETTINGS.items()
    }


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Sin `config_parameter`: con un Boolean, set_param(False) borra el
    # parámetro y "Punto de venta" volvería a su default True. Se guarda
    # "True"/"False" explícito en get_values/set_values.
    pds_edit_defaults = fields.Boolean(string="Permitir editar los valores por defecto")
    pds_show_page_variants = fields.Boolean(string="Pestaña Atributos y variantes")
    pds_show_page_sales = fields.Boolean(string="Pestaña Ventas")
    pds_show_page_purchase = fields.Boolean(string="Pestaña Compras")
    pds_show_page_inventory = fields.Boolean(string="Pestaña Inventario")
    pds_show_page_pos = fields.Boolean(string="Pestaña Punto de venta")

    @api.model
    def get_values(self):
        """Carga los ajustes del formulario de producto desde ir.config_parameter."""
        res = super().get_values()
        for key, value in get_product_form_settings(self.env).items():
            res["pds_" + key] = value
        return res

    def set_values(self):
        """Guarda los ajustes como "True"/"False" y, si se prende la pestaña de
        variantes, activa la funcionalidad nativa de variantes."""
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()
        for key in PRODUCT_FORM_SETTINGS:
            icp.set_param(PARAM_PREFIX + key, str(bool(self["pds_" + key])))
        if self.pds_show_page_variants:
            # Mismo mecanismo que `implied_group` del core: da el grupo nativo
            # de variantes a todos los usuarios internos. Apagar la pestaña no
            # lo quita, igual que antes con el grupo propio.
            self.env.ref("base.group_user").sudo()._apply_group(
                self.env.ref("product.group_product_variant")
            )
