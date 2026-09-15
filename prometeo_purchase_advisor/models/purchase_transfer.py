"""Propuestas de traslado y documentos de Inventario vinculados."""
from datetime import timedelta
from odoo import _, api, fields, models, Command
from odoo.exceptions import AccessError, UserError, ValidationError


class PurchaseTransfer(models.Model):
    _name = 'prometeo.purchase.transfer'
    _description = 'Traslado recomendado'
    _order = 'source_warehouse_id, destination_warehouse_id, product_id, id'

    suggestion_id = fields.Many2one('prometeo.purchase.suggestion', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='suggestion_id.company_id', store=True)
    product_id = fields.Many2one('product.product', required=True, ondelete='restrict')
    source_warehouse_id = fields.Many2one('stock.warehouse', string='Desde', required=True, ondelete='restrict')
    destination_warehouse_id = fields.Many2one('stock.warehouse', string='Hacia', required=True, ondelete='restrict')
    quantity = fields.Float(string='Unidades a trasladar', required=True, digits='Product Unit of Measure')
    picking_id = fields.Many2one('stock.picking', string='Traslado / salida', readonly=True, copy=False, ondelete='restrict')
    receipt_id = fields.Many2one('stock.picking', string='Recepción', readonly=True, copy=False, ondelete='restrict')
    state = fields.Selection([('proposed', 'Propuesto'), ('prepared', 'Preparado'),
                              ('done', 'Recibido'), ('cancel', 'Cancelado')], compute='_compute_state')

    @api.model_create_multi
    def create(self, vals_list):
        """Los documentos solo pueden vincularse desde la preparación verificada."""
        if (self.env.context.get('default_picking_id') or self.env.context.get('default_receipt_id')
                or any(values.get('picking_id') or values.get('receipt_id') for values in vals_list)):
            raise AccessError(_('Los documentos se vinculan únicamente al preparar los traslados.'))
        return super().create([dict(values, picking_id=False, receipt_id=False) for values in vals_list])

    def write(self, values):
        """Protege enlaces frente a RPC, no solo mediante readonly en la vista."""
        if {'picking_id', 'receipt_id'} & values.keys():
            raise AccessError(_('No se pueden reemplazar los documentos del traslado.'))
        if ({'product_id', 'source_warehouse_id', 'destination_warehouse_id', 'quantity', 'suggestion_id'}
                & values.keys() and any(plan.picking_id for plan in self)):
            raise UserError(_('El traslado preparado conserva su origen, destino y cantidad originales.'))
        return super().write(values)

    def unlink(self):
        """Conserva la trazabilidad de documentos preparados incluso al cancelarlos."""
        if any(plan.picking_id for plan in self):
            raise UserError(_('No se pueden eliminar propuestas con traslados preparados.'))
        return super().unlink()

    def _linked_pickings(self):
        """Documentos de estos planes, incluidos sus backorders; no busca documentos ajenos."""
        # Onchange can carry arbitrary readonly values. Trust only persisted links.
        persisted = self._origin
        persisted.check_access('read')
        pickings = (persisted.picking_id | persisted.receipt_id).sudo()
        frontier = pickings
        while frontier:
            frontier = frontier.backorder_ids - pickings
            pickings |= frontier
        return pickings

    @api.depends('picking_id.state', 'receipt_id.state', 'picking_id.backorder_ids.state', 'receipt_id.backorder_ids.state')
    def _compute_state(self):
        """Solo considera recibido cuando termina también la recepción destino."""
        for plan in self:
            if not plan._origin.picking_id:
                plan.state = 'proposed'
            elif 'cancel' in plan._linked_pickings().mapped('state'):
                plan.state = 'cancel'
            elif all(picking.state == 'done' for picking in plan._linked_pickings()):
                plan.state = 'done'
            else:
                plan.state = 'prepared'

    @api.constrains('quantity', 'source_warehouse_id', 'destination_warehouse_id')
    def _check_transfer(self):
        """Evita cantidades inválidas y movimientos hacia el mismo almacén."""
        for plan in self:
            if plan.quantity <= 0 or plan.source_warehouse_id == plan.destination_warehouse_id:
                raise ValidationError(_('El traslado requiere cantidad positiva y almacenes distintos.'))

    def _prepare_pickings(self):
        """Reserva stock con permisos normales, manteniendo el destino explícito."""
        source = self.source_warehouse_id
        destination = self.destination_warehouse_id
        source.ensure_one()
        destination.ensure_one()
        (source | destination).check_access('read')
        cross_company = source.company_id != destination.company_id
        transit = self.env.ref('stock.stock_location_inter_company') if cross_company else destination.lot_stock_id
        if cross_company and transit.company_id:
            raise UserError(_('La ubicación de tránsito entre compañías debe ser compartida.'))
        moves = [Command.create({
            'name': plan.product_id.display_name, 'product_id': plan.product_id.id,
            'product_uom': plan.product_id.uom_id.id, 'product_uom_qty': plan.quantity,
            'location_id': source.lot_stock_id.id, 'location_dest_id': transit.id,
            'company_id': source.company_id.id,
        }) for plan in self]
        picking = self.env['stock.picking'].with_company(source.company_id).create({
            'picking_type_id': (source.out_type_id if cross_company else source.int_type_id).id,
            'company_id': source.company_id.id, 'location_id': source.lot_stock_id.id,
            'location_dest_id': transit.id, 'origin': self.suggestion_id.name,
            # An explicit receipt below identifies the exact destination. No partner-based counterpart.
            'partner_id': False, 'move_ids': moves,
        })
        receipt = self.env['stock.picking']
        if cross_company:
            receipt_moves = [Command.create({
                'name': move.name, 'product_id': move.product_id.id,
                'product_uom': move.product_uom.id, 'product_uom_qty': move.product_uom_qty,
                'company_id': destination.company_id.id, 'location_id': transit.id,
                'location_dest_id': destination.lot_stock_id.id,
                'move_orig_ids': [Command.link(move.id)],
            }) for move in picking.move_ids]
            receipt = self.env['stock.picking'].with_company(destination.company_id).create({
                'picking_type_id': destination.in_type_id.id, 'company_id': destination.company_id.id,
                'location_id': transit.id, 'location_dest_id': destination.lot_stock_id.id,
                'origin': picking.name, 'partner_id': source.company_id.partner_id.id,
                'scheduled_date': fields.Datetime.now() + timedelta(days=self.suggestion_id.transfer_days),
                'move_ids': receipt_moves,
            })
        picking.action_confirm()
        if receipt:
            receipt.action_confirm()
        picking.action_assign()
        if picking.state != 'assigned':
            raise UserError(_('No se pudo reservar todo el traslado desde %(warehouse)s. Recalculá.', warehouse=source.name))
        # Private method is not callable over RPC. Only link documents just created above.
        super(PurchaseTransfer, self).write({'picking_id': picking.id, 'receipt_id': receipt.id})
