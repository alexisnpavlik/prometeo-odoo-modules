# -*- coding: utf-8 -*-
from odoo import models, api

class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    def _get_action(self, action_xmlid):
        action = super(StockPickingType, self)._get_action(action_xmlid)
        if self.code == 'incoming':
            context = dict(action.get('context') or {})
            context['create'] = False
            action['context'] = context
        return action

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def _get_action(self, action_xmlid):
        action = super(StockPicking, self)._get_action(action_xmlid)
        context = dict(action.get('context') or {})
        # Si la accion es para las recepciones entrantes (Receipts)
        if action_xmlid == 'stock.action_picking_tree_incoming' or context.get('restricted_picking_type_code') == 'incoming':
            context['create'] = False
            action['context'] = context
        return action
