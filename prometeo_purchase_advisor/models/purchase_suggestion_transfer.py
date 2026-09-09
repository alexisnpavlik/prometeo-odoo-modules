"""Planifica redistribución de excedentes antes de comprar."""
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare, float_round


class PurchaseSuggestionTransfer(models.Model):
    _inherit = 'prometeo.purchase.suggestion'

    prioritize_transfers = fields.Boolean(string='Transferir antes de comprar', default=True)
    source_warehouse_ids = fields.Many2many(
        'stock.warehouse', 'purchase_suggestion_source_warehouse_rel',
        'suggestion_id', 'warehouse_id', string='Orígenes disponibles',
        help='Almacenes donde buscar excedentes. Vacío busca en todos los almacenes '
             'de las compañías activas. Los orígenes no agregan demanda a esta compra.')
    transfer_plan_ids = fields.One2many('prometeo.purchase.transfer', 'suggestion_id',
                                       string='Traslados', copy=False)
    transfer_picking_ids = fields.Many2many('stock.picking', compute='_compute_transfer_status')
    transfer_picking_count = fields.Integer(compute='_compute_transfer_status')
    pending_transfer_count = fields.Integer(compute='_compute_transfer_status')
    has_purchase_quantity = fields.Boolean(compute='_compute_transfer_status')
    transfer_recompute_required = fields.Boolean(copy=False, readonly=True)
    transfer_documents_snapshot = fields.Json(copy=False, readonly=True)
    transfers_calculated = fields.Boolean(copy=False, readonly=True)

    @api.depends('transfer_plan_ids.picking_id', 'transfer_plan_ids.receipt_id',
                 'line_ids.qty_final')
    def _compute_transfer_status(self):
        """Resume propuestas pendientes y documentos preparados."""
        for suggestion in self:
            plans = suggestion.transfer_plan_ids
            suggestion.transfer_picking_ids = plans._linked_pickings()
            suggestion.transfer_picking_count = len(suggestion.transfer_picking_ids)
            suggestion.pending_transfer_count = len(plans.filtered(lambda p: not p.picking_id))
            suggestion.has_purchase_quantity = any(line.qty_final > 0 for line in suggestion.line_ids)

    def _transfer_warehouses(self):
        """Comprueba el alcance antes de consultar existencias de los orígenes."""
        destinations = self._supply_warehouses()
        sources = self.source_warehouse_ids or self.env['stock.warehouse'].search([
            ('company_id', 'in', self.env.companies.ids)])
        warehouses = destinations | sources
        warehouses.check_access('read')
        if warehouses.company_id - self.env.companies:
            raise AccessError(_('Activá las compañías de los almacenes seleccionados.'))
        return destinations, sources, warehouses

    def _plan_replenishment(self, products=None):
        """Asigna cada unidad física una vez y mantiene la cobertura del donante."""
        self.ensure_one()
        destinations, sources, warehouses = self._transfer_warehouses()
        products = self._candidate_products() if products is None else products
        credits = self._pending_transfer_credits(products, warehouses)
        rows, estimates_by_warehouse, free = {}, {}, {}
        for warehouse in warehouses:
            scoped = self.with_company(warehouse.company_id)
            estimates, demand_models = scoped._estimate_demand(products, warehouse=warehouse)
            estimates_by_warehouse[warehouse.id] = estimates
            rows[warehouse.id] = self._build_line_values(
                products, estimates, demand_models, warehouse=warehouse, include_all=True,
                incoming_adjustments=credits.get(warehouse.id))
            free[warehouse.id] = {
                product.id: product.free_qty for product in products.with_context(
                    warehouse_id=warehouse.id, location=warehouse.lot_stock_id.id)}

        result, proposals = {}, []
        existing = set(self.line_ids.product_id.ids)
        for product in products:
            needs, budgets = {}, {}
            for warehouse in destinations:
                row = rows[warehouse.id].get(product.id)
                if not row:
                    continue
                estimate = estimates_by_warehouse[warehouse.id][product.id]
                include = product.id in existing or self._should_include(
                    product, estimate, row['coverage_days_current'], row['lead_time_days'], row['qty_on_hand'])
                # Cover the need in whole stock-UoM increments before allocating.
                # Rounding each transfer down first can leave an artificial 0.01 purchase.
                needs[warehouse.id] = float_round(
                    max(row['qty_suggested'], 0), precision_rounding=product.uom_id.rounding,
                    rounding_method='UP') if include else 0
            for warehouse in sources | destinations:
                row = rows[warehouse.id].get(product.id)
                if row:
                    # Remove incoming from the forecast surplus: only physical stock can leave.
                    budgets[warehouse.id] = max(min(
                        -row['qty_suggested'] - row['qty_incoming'], free[warehouse.id][product.id]), 0)
            donors = sorted(budgets, key=lambda wid: (wid != self.warehouse_id.id, -budgets[wid], wid))
            targets = sorted(needs, key=lambda wid: (rows[wid][product.id]['coverage_days_current'], wid))
            allocated = 0
            for destination_id in targets:
                for source_id in donors:
                    if source_id == destination_id:
                        continue
                    quantity = float_round(min(needs[destination_id], budgets[source_id]),
                                           precision_rounding=product.uom_id.rounding, rounding_method='DOWN')
                    if quantity <= 0:
                        continue
                    proposals.append({'product_id': product.id, 'source_warehouse_id': source_id,
                                      'destination_warehouse_id': destination_id, 'quantity': quantity})
                    budgets[source_id] -= quantity
                    needs[destination_id] -= quantity
                    allocated += quantity
            quantity = self._apply_supplier_constraints(product, self._pick_seller(product), sum(needs.values()))
            if quantity <= 0 and allocated <= 0 and product.id not in existing:
                continue
            central = rows[self.warehouse_id.id].get(product.id)
            if not central:
                continue
            if self.supply_mode == 'centralized':
                values = self._consolidate_line(
                    [(warehouse, rows[warehouse.id][product.id]) for warehouse in destinations
                     if product.id in rows[warehouse.id]], central, quantity)
            else:
                values = dict(central, qty_suggested=quantity, qty_final=quantity)
            values['qty_to_transfer'] = allocated
            values['explanation'] = _(
                'Transferir primero: %(transfer)s unidades. Comprar el faltante: %(buy)s unidades. '
                'El origen conserva su cobertura y stock de seguridad.\n',
                transfer=round(allocated, 2), buy=round(quantity, 2)) + values['explanation']
            result[product.id] = values
        return result, proposals

    def _run_engine(self):
        """Actualiza únicamente propuestas; los movimientos preparados se conservan."""
        if self.prioritize_transfers:
            metrics, proposals = self._plan_replenishment()
        else:
            metrics, proposals = super()._run_engine(), []
            for values in metrics.values():
                values['qty_to_transfer'] = 0
        self.transfer_plan_ids.filtered(lambda plan: not plan.picking_id).unlink()
        self.env['prometeo.purchase.transfer'].create([
            dict(values, suggestion_id=self.id) for values in proposals])
        return metrics

    def action_compute(self):
        """El cálculo incorpora las entradas/salidas confirmadas de los traslados."""
        result = super().action_compute()
        self.transfer_recompute_required = False
        self.transfers_calculated = True
        for suggestion in self:
            suggestion.transfer_documents_snapshot = suggestion._transfer_documents_signature()
        return result

    def _transfer_documents_signature(self):
        """Detecta cancelaciones, parciales y cambios posteriores a la corrida."""
        return [[picking.id, picking.state,
                 [[move.id, move.state, move.product_id.id, move.product_uom.id, move.product_uom_qty,
                   move.quantity, move.location_id.id, move.location_dest_id.id]
                  for move in picking.move_ids.sorted('id')]]
                for picking in self.transfer_plan_ids._linked_pickings().sorted('id')]

    def _check_transfer_calculation(self):
        """No permite ejecutar un residual basado en movimientos que cambiaron."""
        if self._transfer_documents_signature() != (self.transfer_documents_snapshot or []):
            raise UserError(_('Los traslados cambiaron desde el último cálculo. Recalculá antes de continuar.'))

    def action_prepare_transfers(self):
        """Prepara y reserva, sin validar entregas; exige un cálculo posterior."""
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('stock.group_stock_user'):
            raise AccessError(_('Necesitás permisos de Inventario para preparar los traslados.'))
        self.env.cr.execute('SELECT id FROM prometeo_purchase_suggestion WHERE id = %s FOR UPDATE', [self.id])
        self.env.invalidate_all()
        if self.state not in ('computed', 'confirmed') or self.transfer_recompute_required:
            raise UserError(_('Recalculá la sugerencia antes de preparar traslados.'))
        plans = self.transfer_plan_ids.filtered(lambda plan: not plan.picking_id)
        if not plans:
            raise UserError(_('No hay traslados propuestos pendientes.'))
        if not self.prioritize_transfers or plans.product_id - self._candidate_products():
            raise UserError(_('Cambió el alcance de la sugerencia. Recalculá antes de preparar traslados.'))
        _metrics, fresh = self._plan_replenishment(products=plans.product_id)
        available = defaultdict(float)
        for row in fresh:
            available[(row['product_id'], row['source_warehouse_id'], row['destination_warehouse_id'])] += row['quantity']
        for plan in plans:
            key = (plan.product_id.id, plan.source_warehouse_id.id, plan.destination_warehouse_id.id)
            if float_compare(plan.quantity, available[key], precision_rounding=plan.product_id.uom_id.rounding) > 0:
                raise UserError(_('Cambió el stock disponible o la necesidad. Recalculá la sugerencia.'))
            available[key] -= plan.quantity
        with self.env.cr.savepoint():
            groups = defaultdict(lambda: self.env['prometeo.purchase.transfer'])
            for plan in plans:
                groups[(plan.source_warehouse_id, plan.destination_warehouse_id)] |= plan
            for group in groups.values():
                group._prepare_pickings()
            self.write({'transfer_recompute_required': True, 'state': 'computed'})
        return self.action_view_transfers()

    def _lines_to_order(self):
        """Una propuesta sin reserva no puede reducir una compra ejecutable."""
        self._check_transfer_calculation()
        if self.prioritize_transfers and not self.transfers_calculated:
            raise UserError(_('Recalculá la sugerencia para buscar excedentes antes de comprar. '
                              'Si ya está confirmada, volvé primero a borrador.'))
        if self.transfer_recompute_required or self.pending_transfer_count:
            raise UserError(_('Prepará los traslados propuestos y recalculá antes de generar la compra. '
                              'Si no se van a realizar, desactivá Transferir antes de comprar y recalculá.'))
        return super()._lines_to_order()

    def action_confirm(self):
        """Admite sugerencias cuya necesidad se resuelve solo con traslados."""
        for suggestion in self:
            suggestion._check_transfer_calculation()
            if suggestion.prioritize_transfers and not suggestion.transfers_calculated:
                raise UserError(_('Recalculá la sugerencia para buscar excedentes antes de confirmar.'))
            if suggestion.transfer_recompute_required:
                raise UserError(_('Recalculá después de preparar los traslados y antes de confirmar.'))
            if (suggestion.state == 'computed' and not suggestion.has_purchase_quantity
                    and suggestion.transfer_plan_ids):
                suggestion.state = 'confirmed'
            else:
                super(PurchaseSuggestionTransfer, suggestion).action_confirm()
        return True

    def action_finish_transfers(self):
        """Cierra una propuesta cubierta por movimientos preparados, sin crear compra."""
        self.ensure_one()
        self._check_transfer_calculation()
        if (self.state not in ('computed', 'confirmed') or self.has_purchase_quantity
                or self.pending_transfer_count or self.transfer_recompute_required
                or not self.transfer_plan_ids.filtered(lambda plan: plan.state in ('prepared', 'done'))):
            raise UserError(_('Prepará los traslados y recalculá. Solo podés finalizar así si no queda nada por comprar.'))
        self.state = 'done'
        return self.action_view_transfers()

    def action_view_transfers(self):
        """Abre únicamente los documentos vinculados a esta sugerencia."""
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Traslados de abastecimiento'),
                'res_model': 'stock.picking', 'view_mode': 'list,form',
                'domain': [('id', 'in', self.transfer_picking_ids.ids)]}

    def unlink(self):
        """No pierde los vínculos de Inventario mediante borrado en cascada."""
        if self.transfer_plan_ids.picking_id:
            raise UserError(_('Conservá las sugerencias que ya prepararon traslados para mantener su trazabilidad.'))
        return super().unlink()
