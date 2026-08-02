# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ReportSaleDetails(models.AbstractModel):
    _inherit = "report.point_of_sale.report_saledetails"

    @api.model
    def get_sale_details(
        self, date_start=False, date_stop=False, config_ids=False, session_ids=False, **kwargs
    ):
        """Agrega al informe de sesión el detalle de operaciones controladas
        (eliminaciones, descuentos altos y cambios de precio).

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
                ("event_datetime", ">=", start),
                ("event_datetime", "<=", stop),
            ]
            if config_ids:
                domain += [("pos_config_id", "in", config_ids)]

        logs = self.env["pos.control.log"].sudo().search(domain, order="event_datetime asc")
        type_labels = dict(
            self.env["pos.control.log"]._fields["event_type"].selection
        )

        events = []
        counts = {
            "order": 0, "line": 0, "qty_reduction": 0,
            "high_discount": 0, "price_reduction": 0, "price_increase": 0,
            "refund": 0,
        }
        for log in logs:
            if log.event_type in counts:
                counts[log.event_type] += 1
            events.append(
                {
                    "datetime": log.event_datetime,
                    "user_name": log.user_id.name or "",
                    "type_label": type_labels.get(log.event_type, log.event_type),
                    "product_name": log.product_id.display_name or "",
                    "qty": log.qty_removed,
                    "discount": log.discount_percent,
                    "old_price": log.old_price,
                    "new_price": log.new_price,
                    "reason": log.reason_id.name or "",
                    "note": log.reason_note or "",
                }
            )

        # Reembolsos: fuente nativa (líneas con refunded_orderline_id). Mismo
        # alcance (sesión o rango+config). Se suman al detalle y al resumen.
        refund_domain = [
            ("refunded_orderline_id", "!=", False),
            ("order_id.state", "in", ("paid", "done", "invoiced")),
        ]
        if session_ids:
            refund_domain += [("order_id.session_id", "in", session_ids)]
        else:
            refund_domain += [
                ("order_id.date_order", ">=", start),
                ("order_id.date_order", "<=", stop),
            ]
            if config_ids:
                refund_domain += [("order_id.config_id", "in", config_ids)]

        refund_lines = self.env["pos.order.line"].sudo().search(refund_domain)
        refund_amount = 0.0
        refund_order_ids = set()
        for line in refund_lines:
            refund_amount += line.price_subtotal_incl
            order = line.order_id
            refund_order_ids.add(order.id)
            events.append(
                {
                    "datetime": order.date_order,
                    "user_name": order.user_id.name or "",
                    "type_label": "Reembolso",
                    "product_name": line.product_id.display_name or "",
                    "qty": line.qty,
                    "discount": 0.0,
                    "old_price": 0.0,
                    "new_price": 0.0,
                    "reason": "",
                    "note": order.pos_reference or order.name or "",
                }
            )

        counts["refund"] = len(refund_order_ids)
        events.sort(key=lambda e: e["datetime"] or fields.Datetime.now())

        res["control_events"] = events
        res["control_counts"] = counts
        res["refund_amount"] = refund_amount
        return res
