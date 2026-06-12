from odoo import models
import logging

_logger = logging.getLogger(__name__)


class PosConfig(models.Model):
    _inherit = "pos.config"

    def _loader_params_payment_method(self):
        """
        Extiende el loader del POS para incluir el campo card_id.
        """
        result = super()._loader_params_payment_method()
        _logger.warning("💾 Ejecutando _loader_params_payment_method con campos: %s", result)
        if "fields" in result.get("search_params", {}):
            if "card_id" not in result["search_params"]["fields"]:
                result["search_params"]["fields"].append("card_id")
        else:
            result["search_params"] = {"fields": ["card_id"]}
        return result

    def _load_pos_data_payment_method(self, config_id, search_params):
        """
        Asegura que el campo card_id se cargue correctamente en los datos del POS.
        """
        _logger.warning("⚙️ Ejecutando _load_pos_data_payment_method con search_params: %s", search_params)
        result = super()._load_pos_data_payment_method(config_id, search_params)
        for method in result:
            method_rec = self.env["pos.payment.method"].browse(method["id"])
            method["card_id"] = method_rec.card_id.id or False
        _logger.warning("✅ Métodos de pago enviados: %s", result)
        return result