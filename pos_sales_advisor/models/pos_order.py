from odoo import fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    sales_advisor_id = fields.Many2one(
        "pos.sales.advisor",
        string="Asesor de Venta",
        index=True,
        help="Asesor de venta al que se atribuye esta orden para métricas y compensaciones.",
    )

    def _prepare_refund_values(self, current_session):
        """La devolución hereda el asesor de la orden original para que reste en sus métricas."""
        vals = super()._prepare_refund_values(current_session)
        vals["sales_advisor_id"] = self.sales_advisor_id.id
        return vals
