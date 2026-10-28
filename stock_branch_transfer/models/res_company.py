from odoo import api, models

# Contexto que pone el selector de Destino del traslado
DEST_CONTEXT_KEY = "branch_transfer_dest"


class ResCompany(models.Model):
    _inherit = "res.company"

    def _for_branch_transfer_dest(self):
        """Selector de Destino: lista todas las sucursales, no solo las seleccionadas.

        La regla multiempresa de Odoo limita res.company a las empresas activas, así
        que con una sola sucursal elegida no aparecería ningún destino. Solo se usa
        para buscar y mostrar nombres; no da acceso a datos de la otra empresa.
        """
        if self.env.context.get(DEST_CONTEXT_KEY) and self.env.user._is_internal():
            return self.sudo()
        return self

    @api.model
    def name_search(self, name="", args=None, operator="ilike", limit=100):
        """Autocompletado del selector de Destino."""
        return super(ResCompany, self._for_branch_transfer_dest()).name_search(name, args, operator, limit)

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        """"Buscar más..." del selector de Destino."""
        return super(ResCompany, self._for_branch_transfer_dest()).web_search_read(
            domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit
        )
