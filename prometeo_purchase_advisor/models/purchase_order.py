# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    suggestion_id = fields.Many2one(
        "prometeo.purchase.suggestion", string="Sugerencia de compra",
        readonly=True, index=True, ondelete="set null",
        help="Sugerencia del recomendador que originó esta orden.",
    )

    def _check_advisor_budget(self):
        """Comprueba el conjunto de órdenes de cada sugerencia, sin impuestos."""
        # Lectura interna limitada: confirmar una PO no requiere acceso a métricas
        # protegidas de todas las sucursales. No se devuelve información de la red.
        for suggestion in self.suggestion_id.sudo().filtered('budget_enabled').sorted('id'):
            # Todas las órdenes comparten esta fila. En REPEATABLE READ una
            # modificación concurrente provoca SerializationFailure y Odoo
            # reintenta la transacción con el gasto actualizado.
            self.env.cr.execute('''UPDATE prometeo_purchase_suggestion
                SET budget_revision = COALESCE(budget_revision, 0) + 1 WHERE id = %s''',
                [suggestion.id])
            suggestion.invalidate_recordset(['budget_revision'])
            orders = suggestion.purchase_order_ids.filtered(lambda order: order.state != 'cancel')
            amount = sum(order.currency_id._convert(
                order.amount_untaxed, suggestion.currency_id, suggestion.company_id,
                fields.Date.context_today(suggestion)) for order in orders)
            if suggestion.currency_id.compare_amounts(amount, suggestion.budget_amount) > 0:
                raise UserError(_('Las órdenes vinculadas superan el presupuesto sin impuestos '
                                  'de %(suggestion)s. Revisá sus cantidades y precios.',
                                  suggestion=suggestion.name))

    def button_confirm(self):
        """Editar una orden en borrador no permite saltarse el presupuesto común."""
        self._check_advisor_budget()
        return super().button_confirm()

    def button_approve(self, force=False):
        """La segunda aprobación también verifica el límite vigente."""
        self._check_advisor_budget()
        return super().button_approve(force=force)

    def write(self, vals):
        """No permite aumentar el compromiso de órdenes ya confirmadas sobre el límite."""
        if not self.suggestion_id and not vals.get('suggestion_id'):
            return super().write(vals)
        with self.env.cr.savepoint():
            result = super().write(vals)
            if {'currency_id', 'order_line', 'state'} & vals.keys():
                self.filtered(lambda o: o.state in ('purchase', 'done'))._check_advisor_budget()
        return result


class PurchaseOrderLineBudget(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        """Agregar mercadería a una orden comprometida consume el mismo presupuesto."""
        orders = self.env['purchase.order'].browse([
            vals.get('order_id') or self.env.context.get('default_order_id')
            for vals in vals_list if vals.get('order_id') or self.env.context.get('default_order_id')])
        if not orders.suggestion_id:
            return super().create(vals_list)
        with self.env.cr.savepoint():
            lines = super().create(vals_list)
            lines.order_id.filtered(lambda o: o.state in ('purchase', 'done'))._check_advisor_budget()
        return lines

    def write(self, vals):
        """Valida cantidades, precios y descuentos modificados después de confirmar."""
        if not self.order_id.suggestion_id and not vals.get('order_id'):
            return super().write(vals)
        with self.env.cr.savepoint():
            old_orders = self.order_id
            result = super().write(vals)
            if {'product_qty', 'price_unit', 'discount', 'taxes_id', 'product_uom', 'order_id'} & vals.keys():
                (old_orders | self.order_id).filtered(
                    lambda o: o.state in ('purchase', 'done'))._check_advisor_budget()
        return result
