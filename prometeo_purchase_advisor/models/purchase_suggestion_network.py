"""Abastecimiento directo o centralizado sobre los mismos estimadores de demanda."""
from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PurchaseSuggestionNetwork(models.Model):
    _inherit = "prometeo.purchase.suggestion"

    supply_mode = fields.Selection(
        [("direct", "Compra directa al almacén"),
         ("centralized", "Compra centralizada para sucursales")],
        string="Modalidad", default="direct", required=True, tracking=True,
    )
    demand_warehouse_ids = fields.Many2many(
        "stock.warehouse", "purchase_suggestion_demand_warehouse_rel",
        "suggestion_id", "warehouse_id", string="Sucursales a abastecer",
        help="Su demanda se calcula por separado. La orden se recibe en el almacén "
             "de la sugerencia. Solo se incluyen compañías a las que tenés acceso.",
    )
    transfer_days = fields.Float(
        string="Días de distribución", default=0,
        help="Plazo adicional desde el depósito hasta las sucursales. "
             "Cero significa distribución inmediata; ajustalo si no corresponde.",
    )
    calculation_notes = fields.Text(string="Calidad de los datos", readonly=True, copy=False)
    metric_warehouse_ids = fields.Many2many(
        "stock.warehouse", "purchase_suggestion_metric_warehouse_rel",
        "suggestion_id", "warehouse_id", compute="_compute_metric_warehouses", store=True,
        string="Almacenes de las métricas guardadas",
    )
    has_forbidden_warehouses = fields.Boolean(
        compute="_compute_has_forbidden_warehouses",
        search="_search_has_forbidden_warehouses",
        string="Incluye almacenes de compañías no seleccionadas",
    )

    @api.depends("demand_warehouse_ids.company_id", "metric_warehouse_ids.company_id")
    @api.depends_context("allowed_company_ids", "uid")
    def _compute_has_forbidden_warehouses(self):
        """Evalúa permisos en memoria sin ocultar los almacenes que deben bloquearlos."""
        company_ids = set(self.env.companies.ids)
        for suggestion in self:
            scoped = suggestion.sudo()
            warehouses = scoped.demand_warehouse_ids | scoped.metric_warehouse_ids
            suggestion.has_forbidden_warehouses = any(
                warehouse.company_id.id not in company_ids for warehouse in warehouses
            )

    def _search_has_forbidden_warehouses(self, operator, value):
        """Deja la subconsulta dinámica dentro del compilador SQL, fuera de ir.rule."""
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise ValueError("El filtro de acceso requiere una comparación booleana.")
        forbidden = value if operator == "=" else not value
        query = self.env.user._purchase_advisor_forbidden_suggestions(self.env.companies.ids)
        return [("id", "in" if forbidden else "not in", query)]

    @api.depends("line_ids.params_snapshot")
    def _compute_metric_warehouses(self):
        """Mantiene el alcance de seguridad aunque cambie la selección editable."""
        for suggestion in self:
            warehouse_ids = {
                row["warehouse_id"]
                for line in suggestion.line_ids
                for row in (line.params_snapshot or {}).get("warehouses", [])
                if row.get("warehouse_id")
            }
            suggestion.metric_warehouse_ids = [fields.Command.set(sorted(warehouse_ids))]

    @api.constrains("coverage_days", "transfer_days", "warehouse_id", "demand_warehouse_ids")
    def _check_supply_parameters(self):
        """Impide períodos imposibles y contar el depósito dos veces."""
        for suggestion in self:
            if suggestion.coverage_days <= 0 or suggestion.transfer_days < 0:
                raise ValidationError(_("La cobertura debe ser positiva y la distribución no puede ser negativa."))
            if suggestion.warehouse_id in suggestion.demand_warehouse_ids:
                raise ValidationError(_("El almacén receptor ya se incluye; no lo repitas como sucursal."))

    def _supply_warehouses(self):
        """Almacenes involucrados, comprobados por ORM antes de leer SQL."""
        self.ensure_one()
        warehouses = self.warehouse_id
        if self.supply_mode == "centralized":
            warehouses |= self.demand_warehouse_ids
        warehouses.check_access("read")
        return warehouses

    def action_detect_demand_warehouses(self):
        """Detecta destinos de despachos hechos en los últimos 180 días."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Volvé a borrador para cambiar las sucursales."))
        self.warehouse_id.check_access("read")
        candidates = self.env["stock.warehouse"].search([
            ("company_id", "in", self.env.companies.ids),
            ("id", "!=", self.warehouse_id.id),
        ])
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT DISTINCT target.id
              FROM stock_move move
              JOIN stock_location src ON src.id = move.location_id
              JOIN stock_location dest ON dest.id = move.location_dest_id
              LEFT JOIN stock_picking picking ON picking.id = move.picking_id
              JOIN stock_warehouse target ON target.id = ANY(%(candidates)s)
              JOIN stock_location target_root ON target_root.id = target.view_location_id
              JOIN res_company company ON company.id = target.company_id
             WHERE move.state = 'done' AND move.product_qty > 0
               AND move.company_id = %(company)s
               AND src.usage = 'internal' AND src.parent_path LIKE %(source)s
               AND move.date >= %(since)s
               AND (
                    (dest.usage = 'internal' AND dest.parent_path LIKE target_root.parent_path || '%%')
                    OR (dest.usage IN ('transit', 'customer')
                        AND COALESCE(picking.partner_id, move.partner_id) = company.partner_id
                        AND 1 = (SELECT COUNT(*) FROM stock_warehouse same_company
                                  WHERE same_company.company_id = target.company_id AND same_company.active))
               )
        """, {"candidates": candidates.ids, "company": self.company_id.id,
              "source": self.warehouse_id.view_location_id.parent_path + "%",
              "since": fields.Datetime.now() - timedelta(days=180)})
        self.demand_warehouse_ids = [fields.Command.set([row[0] for row in self.env.cr.fetchall()])]
        return True

    def _run_engine(self):
        """Consolida faltantes locales y descuenta la disponibilidad del central una vez."""
        self.ensure_one()
        warehouses = self._supply_warehouses()
        if self.supply_mode != "centralized":
            return super()._run_engine()
        if not self.demand_warehouse_ids:
            raise UserError(_("Detectá o seleccioná las sucursales a abastecer antes de calcular."))
        products = self._candidate_products()
        transfer_credits = self._pending_transfer_credits(products, warehouses)
        by_product = defaultdict(list)
        for warehouse in warehouses:
            estimates, demand_models = self.with_company(warehouse.company_id)._estimate_demand(
                products, warehouse=warehouse)
            metrics = self._build_line_values(
                products, estimates, demand_models, warehouse=warehouse, include_all=True,
                incoming_adjustments=transfer_credits.get(warehouse.id))
            for product_id, values in metrics.items():
                by_product[product_id].append((warehouse, values))

        result = {}
        existing = set(self.line_ids.product_id.ids)
        for product in products:
            rows = by_product[product.id]
            if not rows:
                continue
            central = next(values for warehouse, values in rows if warehouse == self.warehouse_id)
            shortage = central["qty_suggested"] + sum(
                max(values["qty_suggested"], 0)
                for warehouse, values in rows if warehouse != self.warehouse_id)
            qty = self._apply_supplier_constraints(product, self._pick_seller(product), shortage)
            if qty <= 0 and product.id not in existing:
                continue
            result[product.id] = self._consolidate_line(rows, central, qty)
        return result

    def _pending_transfer_credits(self, products, warehouses):
        """Acredita traslados preparados que aún no tienen recepción contraparte.

        stock_intercompany crea la recepción al despachar. Hasta ese momento
        el origen ya tiene una salida comprometida, pero al destino le falta
        la entrada: sin esta compensación se compraría dos veces el traslado.
        """
        self.ensure_one()
        counterpart_filter = ""
        if "counterpart_of_move_id" in self.env["stock.move"]._fields:
            counterpart_filter = """
                AND NOT EXISTS (SELECT 1 FROM stock_move counterpart
                                 WHERE counterpart.counterpart_of_move_id = move.id
                                   AND counterpart.state NOT IN ('cancel', 'draft'))
            """
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT target.id, move.product_id, SUM(move.product_qty)
              FROM stock_move move
              JOIN stock_location src ON src.id = move.location_id
              JOIN stock_location dest ON dest.id = move.location_dest_id
              LEFT JOIN stock_picking picking ON picking.id = move.picking_id
              JOIN stock_warehouse target ON target.id = ANY(%(warehouses)s)
              JOIN res_company company ON company.id = target.company_id
             WHERE move.state IN ('waiting', 'confirmed', 'partially_available', 'assigned')
               AND move.product_id = ANY(%(products)s)
               AND move.company_id = ANY(%(companies)s)
               AND src.usage = 'internal' AND src.parent_path LIKE ANY(%(paths)s)
               AND dest.usage IN ('transit', 'customer')
               AND COALESCE(picking.partner_id, move.partner_id) = company.partner_id
               AND company.id != move.company_id
               AND 1 = (SELECT COUNT(*) FROM stock_warehouse same_company
                         WHERE same_company.company_id = target.company_id AND same_company.active)
               AND NOT EXISTS (
                    SELECT 1 FROM stock_move_move_rel rel
                    JOIN stock_move receipt ON receipt.id = rel.move_dest_id
                     WHERE rel.move_orig_id = move.id AND receipt.state NOT IN ('cancel', 'draft'))
               {counterpart_filter}
             GROUP BY target.id, move.product_id
        """.format(counterpart_filter=counterpart_filter), {
            "warehouses": warehouses.ids, "products": products.ids,
            "companies": warehouses.company_id.ids,
            "paths": [warehouse.view_location_id.parent_path + "%" for warehouse in warehouses],
        })
        credits = defaultdict(dict)
        for warehouse_id, product_id, qty in self.env.cr.fetchall():
            credits[warehouse_id][product_id] = float(qty)
        return credits

    def _consolidate_line(self, rows, central, qty):
        """Explicación auditable: stock, entradas y necesidad por sucursal."""
        self.ensure_one()
        values = dict(central, qty_suggested=qty, qty_final=qty)
        values["adu"] = sum(row["adu"] for _warehouse, row in rows)
        # Suma conservadora: no supone independencia estadística entre sucursales.
        values["sigma"] = sum(row["sigma"] for _warehouse, row in rows)
        values["safety_stock"] = sum(row["safety_stock"] for _warehouse, row in rows)
        values["qty_on_hand"] = sum(max(row["qty_on_hand"], 0) for _warehouse, row in rows)
        values["qty_incoming"] = sum(row["qty_incoming"] for _warehouse, row in rows)
        relevant = [row for _warehouse, row in rows if row["adu"] > 0]
        values["confidence"] = min((row["confidence"] for row in relevant), default=0)
        # El exceso de una sucursal no protege a las otras de un quiebre.
        values["coverage_days_current"] = min(
            (row["coverage_days_current"] for row in relevant), default=9999)
        details, warnings, snapshot = [], [], []
        for warehouse, row in rows:
            need = max(row["qty_suggested"], 0)
            details.append(_(
                "%(warehouse)s: %(adu)s u/día; stock %(stock)s; entradas %(incoming)s; faltante %(need)s.",
                warehouse=warehouse.name, adu=round(row["adu"], 3),
                stock=round(row["qty_on_hand"], 2), incoming=round(row["qty_incoming"], 2),
                need=round(need, 2)))
            if row["warnings"]:
                warnings.append("%s: %s" % (warehouse.name, row["warnings"]))
            snapshot.append({"warehouse_id": warehouse.id, "warehouse_name": warehouse.name,
                             "adu": row["adu"], "qty_on_hand": row["qty_on_hand"],
                             "qty_incoming": row["qty_incoming"], "net_requirement": row["qty_suggested"],
                             "parameters": row["params_snapshot"]})
        values["params_snapshot"] = dict(
            central["params_snapshot"], supply_mode="centralized", warehouses=snapshot,
            transfer_days=self.transfer_days)
        values["explanation"] = _(
            "Compra para recibir en %(warehouse)s. Se suman los faltantes de las sucursales "
            "y se descuenta el stock libre del depósito. El excedente de una sucursal "
            "no se asigna a otra. Los mínimos y bultos se aplican una sola vez.\n",
            warehouse=self.warehouse_id.name) + "\n".join(details)
        values["warnings"] = "\n".join(warnings) or False
        return values

    def action_compute(self):
        """Muestra las limitaciones del catálogo además del resultado numérico."""
        result = super().action_compute()
        for suggestion in self:
            suggestion.calculation_notes = suggestion._data_quality_notes()
        return result

    def _data_quality_notes(self):
        """Advierte sobre proveedores faltantes y antigüedad de los movimientos."""
        self.ensure_one()
        warehouses = self._supply_warehouses()
        self.env.cr.execute("""
            SELECT COUNT(DISTINCT move.product_id) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM product_supplierinfo seller
                        WHERE seller.product_tmpl_id = product.product_tmpl_id
                          AND (seller.product_id IS NULL OR seller.product_id = product.id))),
                   MAX(move.date)
              FROM stock_move move
              JOIN product_product product ON product.id = move.product_id
              JOIN stock_location src ON src.id = move.location_id
              JOIN stock_location dest ON dest.id = move.location_dest_id
              LEFT JOIN stock_picking picking ON picking.id = move.picking_id
             WHERE move.state = 'done' AND move.company_id = ANY(%s)
               AND src.usage = 'internal' AND src.parent_path LIKE ANY(%s)
               AND dest.usage = 'customer' AND move.date >= %s
               AND NOT EXISTS (SELECT 1 FROM res_company company
                               WHERE company.partner_id = COALESCE(picking.partner_id, move.partner_id))
        """, (warehouses.company_id.ids,
              [warehouse.view_location_id.parent_path + "%" for warehouse in warehouses],
              fields.Datetime.now() - timedelta(days=90)))
        missing, last_sale = self.env.cr.fetchone()
        notes = []
        if missing:
            notes.append(_(
                "%(count)s productos con ventas en los últimos 90 días no tienen proveedor "
                "asignado. La falta de proveedor no los excluye del cálculo. "
                "Asigná uno a las líneas a comprar antes de generar las órdenes.", count=missing))
        if last_sale and last_sale < fields.Datetime.now() - timedelta(days=2):
            notes.append(_("La última salida a cliente registrada es del %(date)s. "
                           "Verificá que los movimientos estén actualizados.", date=last_sale))
        if self.supply_mode == "centralized":
            notes.append(_("Las sucursales seleccionadas se abastecen con esta compra. "
                           "Las entradas confirmadas se descuentan, incluidos los traslados. "
                           "Las órdenes en borrador todavía no reservan abastecimiento. "
                           "Revisá las recepciones pendientes antes de repetir una compra."))
        return "\n".join(notes) or False
