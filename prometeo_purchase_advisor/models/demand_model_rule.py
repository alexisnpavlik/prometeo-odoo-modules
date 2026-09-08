# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class PrometeoDemandModelRule(models.Model):
    _name = "prometeo.demand.model.rule"
    _description = "Regla de asignación de modelo de demanda"
    _order = "sequence, id"

    sequence = fields.Integer(string="Secuencia", default=10)
    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(string="Activa", default=True)
    company_id = fields.Many2one(
        "res.company", string="Compañía",
        default=lambda self: self.env.company,
    )
    model_id = fields.Many2one(
        "prometeo.demand.model", string="Modelo de demanda", required=True,
        ondelete="cascade",
    )
    domain = fields.Char(
        string="Dominio", default="[]",
        help="Dominio sobre product.product. Vacío o [] matchea todos los productos.",
    )
    abc_class = fields.Selection(
        [("a", "A"), ("b", "B"), ("c", "C")], string="Clase ABC",
        help="Si se define, la regla solo aplica a productos de esta clase.",
    )
    xyz_class = fields.Selection(
        [("x", "X"), ("y", "Y"), ("z", "Z")], string="Clase XYZ",
        help="Si se define, la regla solo aplica a productos de esta clase.",
    )
    min_history_days = fields.Integer(
        string="Historia mínima (días)",
        help="Si se define, la regla solo aplica a productos con al menos esta "
             "cantidad de días de historia.",
    )

    @api.constrains("domain")
    def _check_domain(self):
        """Un dominio que no parsea rompe toda la corrida: se valida al guardar."""
        for rule in self:
            try:
                parsed = safe_eval(rule.domain or "[]")
                self.env["product.product"].search_count(parsed, limit=1)
            except Exception as e:
                raise ValidationError(_(
                    "El dominio de la regla '%(name)s' no es válido: %(error)s",
                    name=rule.name, error=e,
                ))

    def _matches(self, product, history_days=None):
        """¿Esta regla aplica al producto?

        `history_days` se pasa cuando ya se conoce (durante una corrida). Si es
        None y la regla exige historia mínima, la regla no matchea: es preferible
        caer al default antes que asumir historia que no se midió.
        """
        self.ensure_one()
        if self.abc_class and product.abc_class != self.abc_class:
            return False
        if self.xyz_class and product.xyz_class != self.xyz_class:
            return False
        if self.min_history_days:
            if history_days is None or history_days < self.min_history_days:
                return False
        parsed = safe_eval(self.domain or "[]")
        if parsed:
            return bool(product.filtered_domain(parsed))
        return True

    @api.model
    def _resolve_model_for_products(self, products, history_days_by_product=None):
        """Resuelve el modelo de demanda de cada producto por cascada.

        Orden: override del producto, override de la categoría, primera regla
        que matchea, default de la compañía. Devuelve {product_id: demand_model}.
        """
        history_days_by_product = history_days_by_product or {}
        rules = self.search([("company_id", "in", [False] + self.env.companies.ids)])
        default_model = self.env["res.company"]._prometeo_default_demand_model()
        result = {}
        for product in products:
            model = product.demand_model_id or product.categ_id.demand_model_id
            if not model:
                history = history_days_by_product.get(product.id)
                for rule in rules:
                    if rule._matches(product, history_days=history):
                        model = rule.model_id
                        break
            result[product.id] = model or default_model
        return result
