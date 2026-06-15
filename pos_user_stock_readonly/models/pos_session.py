# -*- coding: utf-8 -*-
from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _load_pos_data(self, data):
        """Muestra el botón de entrada/salida de efectivo al vendedor restringido.

        El POS solo muestra la opción si el usuario tiene el grupo
        Contabilidad/Facturación; se habilita el flag también para el
        grupo restringido, cuya operación se ejecuta vía try_cash_in_out.
        """
        result = super()._load_pos_data(data)
        if not result["data"][0].get("_has_cash_move_perm"):
            result["data"][0]["_has_cash_move_perm"] = self.env.user.has_group(
                "pos_user_stock_readonly.group_pos_user_stock_readonly"
            )
        return result

    def try_cash_in_out(self, _type, amount, reason, extras):
        """Permite retiros/ingresos de efectivo al vendedor POS restringido.

        El asiento del movimiento de efectivo se registra sin sudo en el
        método original, y su publicación exige el grupo Contabilidad/
        Facturación. Para no otorgar ese grupo completo al cajero, la
        operación se ejecuta con sudo únicamente cuando el usuario tiene
        el grupo restringido y carece de permisos de facturación.
        """
        restricted = self.env.user.has_group(
            "pos_user_stock_readonly.group_pos_user_stock_readonly"
        ) and not self.env.user.has_group("account.group_account_invoice")
        if restricted:
            return super(PosSession, self.sudo()).try_cash_in_out(
                _type, amount, reason, extras
            )
        return super().try_cash_in_out(_type, amount, reason, extras)
