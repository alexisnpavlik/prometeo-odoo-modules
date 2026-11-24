from odoo import api, fields, models

PARAM_EDIT_SALE_PRICE = "purchase_auto_update_cost.edit_sale_price"


def edit_sale_price_enabled(env):
    """Indica si desde compras se edita el precio de venta; sin parámetro vale activado."""
    return env["ir.config_parameter"].sudo().get_param(PARAM_EDIT_SALE_PRICE, "1") != "0"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Sin config_parameter: un booleano en False borra el parámetro y volvería al
    # valor por defecto (activado). Se guarda "1"/"0" a mano.
    purchase_edit_sale_price = fields.Boolean("Editar el precio de venta desde compras")

    @api.model
    def get_values(self):
        """Lee la opción de editar el precio de venta."""
        res = super().get_values()
        res["purchase_edit_sale_price"] = edit_sale_price_enabled(self.env)
        return res

    def set_values(self):
        """Guarda la opción como "1"/"0"."""
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            PARAM_EDIT_SALE_PRICE, "1" if self.purchase_edit_sale_price else "0"
        )
