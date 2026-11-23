# -*- coding: utf-8 -*-

from odoo import _, api, models
from odoo.exceptions import UserError

from .simplify_options import is_option_active


class UomUom(models.Model):
    _inherit = "uom.uom"

    @api.model_create_multi
    def create(self, vals_list):
        """Con la opción activa, solo el administrador crea unidades de medida.

        Se bloquea en el ORM y no en las vistas para cubrir también la creación
        rápida desde cualquier campo de unidad.
        """
        if (
            not self.env.su
            and not self.env.user.has_group("base.group_system")
            and is_option_active(self.env, "block_uom_create")
        ):
            raise UserError(_("No está permitido crear unidades de medida. Elegí una de las existentes."))
        return super().create(vals_list)
