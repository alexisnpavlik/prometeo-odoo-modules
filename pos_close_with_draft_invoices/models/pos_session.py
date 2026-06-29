import logging

from odoo import models

_logger = logging.getLogger(__name__)


class PosSession(models.Model):
    _inherit = "pos.session"

    def _check_invoices_are_posted(self):
        """Permite cerrar la sesión aunque queden facturas en borrador.

        El core de Odoo lanza un UserError cuando alguna factura de las
        órdenes de la sesión no está en estado 'posted', lo que impide
        cerrar la caja. Acá solo registramos las facturas afectadas en el
        log y dejamos continuar el cierre; las facturas quedan intactas en
        borrador para regularizarlas luego.
        """
        unposted = self._get_closed_orders().account_move.filtered(
            lambda move: move.state != "posted"
        )
        if unposted:
            _logger.warning(
                "Cierre de sesión %s permitido con %s factura(s) sin postear: %s",
                self.name,
                len(unposted),
                unposted.mapped("name"),
            )
        return True
