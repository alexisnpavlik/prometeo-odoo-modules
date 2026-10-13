# -*- coding: utf-8 -*-

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# El nombre de las ubicaciones no es traducible: queda en el idioma con el que
# se creó la base. Estos son los nombres en inglés que crea stock.
LOCATION_NAMES_ES = {
    "Physical Locations": "Ubicaciones físicas",
    "Partners": "Contactos",
    "Customers": "Clientes",
    "Vendors": "Proveedores",
    "Virtual Locations": "Ubicaciones virtuales",
    "Inventory adjustment": "Ajuste de inventario",
    "Production": "Producción",
    "Scrap": "Desecho",
    "Inter-company transit": "Tránsito entre empresas",
}


class StockLocation(models.Model):
    _inherit = "stock.location"

    @api.model
    def _simplify_translate_location_names(self):
        """Renombra al español las ubicaciones de stock que siguen en inglés."""
        locations = self.with_context(active_test=False).sudo().search(
            [("name", "in", list(LOCATION_NAMES_ES))]
        )
        for location in locations:
            location.name = LOCATION_NAMES_ES[location.name]
        if locations:
            _logger.info("web_menu_simplify: %s ubicaciones renombradas al español", len(locations))
