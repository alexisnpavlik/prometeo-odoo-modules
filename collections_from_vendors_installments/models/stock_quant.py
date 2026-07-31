# -*- coding: utf-8 -*-
from odoo import _, api, models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    @api.model
    def cvi_action_my_stock(self):
        """Acción que le muestra al vendedor la mercadería que tiene en la calle (HU-02).

        El dominio depende de la ubicación del usuario que la abre, así que no se puede
        declarar en un ir.actions.act_window estático: se arma acá y se expone por un
        ir.actions.server.

        Un vendedor que todavía no retiró nada no tiene ubicación creada. En ese caso
        devolvemos un dominio que no matchea nada en vez de crearla: abrir un listado no
        debería tener efectos colaterales sobre el stock.
        """
        location = self.env.user.cvi_stock_location_id
        return {
            "type": "ir.actions.act_window",
            "name": _("Mi mercadería"),
            "res_model": "stock.quant",
            "view_mode": "list",
            "views": [(
                self.env.ref(
                    "collections_from_vendors_installments.view_cvi_my_stock_list"
                ).id,
                "list",
            )],
            "search_view_id": [self.env.ref(
                "collections_from_vendors_installments.view_cvi_vendor_stock_search"
            ).id],
            "domain": (
                [("location_id", "=", location.id)] if location else [("id", "=", False)]
            ),
            "context": {"search_default_filter_with_stock": 1},
            "help": (
                "<p class='o_view_nocontent_smiling_face'>No tenés mercadería en la calle</p>"
                "<p>Acá vas a ver los muebles que retiraste de fábrica y todavía no "
                "vendiste ni devolviste.</p>"
            ),
        }
