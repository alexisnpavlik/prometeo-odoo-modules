# -*- coding: utf-8 -*-
from odoo import api, models


class ReportSaleDetails(models.AbstractModel):
    _inherit = "report.point_of_sale.report_saledetails"

    @api.model
    def get_sale_details(
        self, date_start=False, date_stop=False, config_ids=False, session_ids=False, **kwargs
    ):
        """Agrega al informe de sesión el detalle de eliminaciones registradas.

        Usa el mismo alcance que el reporte base: por sesión si viene
        session_ids, si no por rango de fechas (+ config).
        """
        res = super().get_sale_details(
            date_start=date_start,
            date_stop=date_stop,
            config_ids=config_ids,
            session_ids=session_ids,
            **kwargs,
        )

        if session_ids:
            domain = [("session_id", "in", session_ids)]
        else:
            start, stop = self._get_date_start_and_date_stop(date_start, date_stop)
            domain = [
                ("deletion_datetime", ">=", start),
                ("deletion_datetime", "<=", stop),
            ]
            if config_ids:
                domain += [("pos_config_id", "in", config_ids)]

        logs = self.env["pos.deletion.log"].sudo().search(domain, order="deletion_datetime asc")
        type_labels = dict(
            self.env["pos.deletion.log"]._fields["deletion_type"].selection
        )

        deletions = []
        counts = {"order": 0, "line": 0, "qty_reduction": 0}
        for log in logs:
            if log.deletion_type in counts:
                counts[log.deletion_type] += 1
            deletions.append(
                {
                    "datetime": log.deletion_datetime,
                    "user_name": log.user_id.name or "",
                    "type_label": type_labels.get(log.deletion_type, log.deletion_type),
                    "product_name": log.product_id.display_name or "",
                    "qty": log.qty_removed,
                    "reason": log.reason_id.name or "",
                    "note": log.reason_note or "",
                }
            )

        res["deletions"] = deletions
        res["deletions_count"] = counts
        return res
