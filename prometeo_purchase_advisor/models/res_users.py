from odoo import models
from odoo.tools import SQL


class ResUsers(models.Model):
    _inherit = "res.users"

    def _purchase_advisor_forbidden_suggestions(self, company_ids):
        """Subconsulta de autorización usada por el search del campo de acceso.

        No se inserta SQL en ir.rule: filtered_domain evalúa esa regla en Python.
        La búsqueda sigue siendo dinámica para proteger almacenes nuevos y tanto
        la selección actual como las métricas guardadas de un cálculo anterior.
        """
        suggestion_fields = self.env["prometeo.purchase.suggestion"]._fields
        return SQL("""(
            SELECT scope.suggestion_id
              FROM (
                    SELECT suggestion_id, warehouse_id FROM %s
                    UNION
                    SELECT suggestion_id, warehouse_id FROM %s
                    UNION
                    SELECT suggestion_id, warehouse_id FROM %s
                   ) scope
              JOIN %s warehouse ON warehouse.id = scope.warehouse_id
             WHERE NOT warehouse.company_id = ANY(%s)
        )""", SQL("purchase_suggestion_demand_warehouse_rel",
                  to_flush=suggestion_fields["demand_warehouse_ids"]),
             SQL("purchase_suggestion_metric_warehouse_rel",
                 to_flush=suggestion_fields["metric_warehouse_ids"]),
             SQL("purchase_suggestion_source_warehouse_rel",
                 to_flush=suggestion_fields["source_warehouse_ids"]),
             SQL("stock_warehouse", to_flush=self.env["stock.warehouse"]._fields["company_id"]),
             company_ids)
