from odoo import models
from odoo.tools import SQL


class ResUsers(models.Model):
    _inherit = "res.users"

    def _purchase_advisor_forbidden_suggestions(self, company_ids):
        """Subconsulta de autorización evaluada en cada lectura, sin sudo.

        La regla cachea SQL, no una lista de IDs: los almacenes creados después
        siguen protegidos. Se comprueba tanto la selección como las métricas
        persistidas, que pueden pertenecer a un cálculo anterior.
        """
        suggestion_fields = self.env["prometeo.purchase.suggestion"]._fields
        return SQL("""(
            SELECT scope.suggestion_id
              FROM (
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
             SQL("stock_warehouse", to_flush=self.env["stock.warehouse"]._fields["company_id"]),
             company_ids)
