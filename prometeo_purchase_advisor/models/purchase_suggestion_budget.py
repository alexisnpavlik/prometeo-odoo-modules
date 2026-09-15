# -*- coding: utf-8 -*-
"""Presupuesto de mercadería: asignación por prioridad y límite al comprar."""
import math
from fractions import Fraction

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class PurchaseSuggestionBudget(models.Model):
    _inherit = 'prometeo.purchase.suggestion'

    budget_enabled = fields.Boolean(string='Limitar por presupuesto', tracking=True)
    budget_amount = fields.Monetary(
        string='Presupuesto sin impuestos', tracking=True,
        help='Máximo para esta sugerencia, en la moneda de la compañía. Cero no permite compras.')
    budget_used = fields.Monetary(string='Mercadería asignada', compute='_compute_budget_totals')
    budget_remaining = fields.Monetary(string='Disponible', compute='_compute_budget_totals')
    budget_exceeded = fields.Boolean(compute='_compute_budget_totals')
    budget_revision = fields.Integer(default=0, readonly=True, copy=False)

    @api.depends('line_ids.subtotal', 'budget_amount', 'currency_id',
                 'line_ids.supplier_id', 'line_ids.product_id.supplier_taxes_id',
                 'line_ids.product_id.supplier_taxes_id.amount',
                 'line_ids.product_id.supplier_taxes_id.price_include')
    def _compute_budget_totals(self):
        """Redondea cada línea como una línea monetaria de compra."""
        for suggestion in self:
            currency = suggestion.currency_id or self.env.company.currency_id
            used = sum(line._budget_line_amount() for line in suggestion.line_ids)
            suggestion.budget_used = used
            suggestion.budget_remaining = suggestion.budget_amount - used
            suggestion.budget_exceeded = currency.compare_amounts(used, suggestion.budget_amount) > 0

    @api.constrains('budget_amount')
    def _check_budget_amount(self):
        """El límite admite cero, pero nunca saldos negativos o infinitos."""
        for suggestion in self:
            if not math.isfinite(suggestion.budget_amount) or suggestion.budget_amount < 0:
                raise ValidationError(_('El presupuesto debe ser un importe finito mayor o igual a cero.'))

    def _check_budget(self):
        """Un precio desconocido no puede interpretarse como mercadería gratis."""
        for suggestion in self.filtered('budget_enabled'):
            for line in suggestion.line_ids:
                if not math.isfinite(line.qty_final) or line.qty_final < 0:
                    raise UserError(_('No se admiten cantidades negativas o inválidas con presupuesto.'))
                if line.qty_final > 0 and (not math.isfinite(line.price_unit) or line.price_unit <= 0):
                    raise UserError(_('Completá un precio positivo para %(product)s antes de comprar.',
                                      product=line.product_id.display_name))
                if line.qty_final > 0 and line._budget_line_amount() < 0:
                    raise UserError(_('El importe neto de mercadería no puede ser negativo.'))
            if suggestion.budget_exceeded:
                raise UserError(_('El total de mercadería supera el presupuesto. Ajustá cantidades '
                                  'o usá «Ajustar al presupuesto» antes de continuar.'))

    def _budget_sort_key(self, line):
        """Prioridad elegida, riesgo de quiebre, cobertura y rotación; desempate estable."""
        return ({'high': 0, 'normal': 1, 'low': 2}[line.budget_priority],
                not (line.coverage_days_current < line.lead_time_days),
                line.coverage_days_current, -line.adu, line.product_id.id, line.id)

    def _budget_lot_limits(self, line):
        """Lote compatible con UoM de stock, compra y bulto; mínimo del proveedor."""
        product = line.product_id
        quanta = [product.uom_id.rounding or .01,
                  product.uom_po_id._compute_quantity(
                      product.uom_po_id.rounding or .01, product.uom_id, round=False)]
        packs = product.packaging_ids.filtered(lambda p: p.purchase and p.qty > 0)
        if packs:
            quanta.append(min(packs.mapped('qty')))
        fractions = [Fraction(str(round(q, 10))).limit_denominator(1000000) for q in quanta]
        denominator = math.lcm(*(f.denominator for f in fractions))
        quantum = math.lcm(*(f.numerator * (denominator // f.denominator) for f in fractions)) / denominator
        today = fields.Date.context_today(self)
        sellers = product.seller_ids.filtered(lambda s:
            s.partner_id == line.supplier_id and
            (not s.product_id or s.product_id == product) and
            (not s.date_start or s.date_start <= today) and
            (not s.date_end or s.date_end >= today))
        own = sellers.filtered(lambda s: s.company_id == self.company_id)
        seller = (own or sellers).sorted(lambda s: (s.sequence, s.price, s.id))[:1]
        minimum = seller.product_uom._compute_quantity(
            seller.min_qty, product.uom_id, round=False) if seller else 0
        return quantum, max(minimum, quantum)

    def _allocate_budget(self, include_manual=False):
        """Asigna lotes completos sin superar el límite; las ediciones se reservan al recalcular."""
        self.ensure_one()
        currency = self.currency_id
        reserved = self.line_ids.filtered(lambda l: l.is_manual or l.was_edited) if not include_manual else self.line_ids.browse()
        available = max(self.budget_amount - sum(l._budget_line_amount() for l in reserved), 0)
        for line in reserved:
            line.budget_note = _('Cantidad manual conservada; también consume presupuesto.')
        for line in (self.line_ids - reserved).sorted(key=self._budget_sort_key):
            desired = max(line.qty_final if (line.is_manual or line.was_edited) else line.qty_suggested, 0)
            price = line.price_unit
            if not line.price_in_stock_uom:
                price = line.product_id.uom_po_id._compute_price(price, line.product_id.uom_id)
            quantity = 0.0
            note = _('Sin necesidad de compra.')
            if desired > 0 and (not line.supplier_id or not math.isfinite(price) or price <= 0):
                note = _('Sin asignación: falta proveedor o precio positivo.')
            elif desired > 0:
                quantum, minimum = self._budget_lot_limits(line)
                # Buscar por lotes evita exceder el límite por redondeos monetarios.
                low, high = 0, math.floor((desired + 1e-9) / quantum)
                while low < high:
                    mid = (low + high + 1) // 2
                    if currency.compare_amounts(line._budget_line_amount(mid * quantum), available) <= 0:
                        low = mid
                    else:
                        high = mid - 1
                quantity = low * quantum
                if float_compare(quantity, minimum, precision_rounding=line.product_id.uom_id.rounding) < 0:
                    quantity = 0.0
                available -= line._budget_line_amount(quantity)
                note = (_('Cantidad completa dentro del presupuesto.') if quantity >= desired else
                        _('Cantidad reducida por presupuesto o lote mínimo. Prioridad: %(priority)s.',
                          priority=dict(line._fields['budget_priority'].selection)[line.budget_priority]))
            line.write({'qty_final': quantity, 'budget_allocated_qty': quantity,
                        'budget_adjusted': True, 'budget_note': note})

    def action_apply_budget(self):
        """El botón autoriza redistribuir también las cantidades editadas manualmente."""
        for suggestion in self:
            if not suggestion.budget_enabled or suggestion.state not in ('draft', 'computed'):
                raise UserError(_('Activá el presupuesto en una sugerencia en borrador o calculada.'))
            suggestion._allocate_budget(include_manual=True)
        return True

    def _apply_metrics(self, metrics):
        """Distribuye presupuesto después de calcular la necesidad directa o consolidada."""
        result = super()._apply_metrics(metrics)
        if self.budget_enabled:
            self._allocate_budget()
        else:
            self.line_ids.write({'budget_adjusted': False, 'budget_note': False})
        return result

    def action_confirm(self):
        """No confirma una propuesta que excede el límite configurado."""
        self._check_budget()
        return super().action_confirm()

    def action_create_purchase_orders(self):
        """Verifica también los importes reales tras conversión de moneda y unidad."""
        self._check_budget()
        with self.env.cr.savepoint():
            result = super().action_create_purchase_orders()
            self.purchase_order_ids._check_advisor_budget()
        return result


class PurchaseSuggestionLineBudget(models.Model):
    _inherit = 'prometeo.purchase.suggestion.line'

    budget_priority = fields.Selection(
        [('high', 'Alta'), ('normal', 'Normal'), ('low', 'Baja')],
        string='Prioridad', default='normal', required=True,
        help='Se usa primero esta prioridad; luego riesgo de quiebre, cobertura y rotación.')
    budget_adjusted = fields.Boolean(readonly=True, copy=False)
    budget_allocated_qty = fields.Float(readonly=True, copy=False, digits='Product Unit of Measure')
    budget_note = fields.Char(string='Asignación de presupuesto', readonly=True, copy=False)

    def _budget_line_amount(self, quantity=None):
        """Neto de impuestos con la unidad y posición fiscal que usará la compra."""
        self.ensure_one()
        line = self.with_company(self.company_id or self.env.company)
        quantity = line.qty_final if quantity is None else quantity
        currency = line.currency_id or self.env.company.currency_id
        if not line.product_id:
            return currency.round(quantity * line.price_unit)
        product = line.product_id
        price = line.price_unit
        if line.price_in_stock_uom:
            price = product.uom_id._compute_price(price, product.uom_po_id)
        purchase_qty = product.uom_id._compute_quantity(quantity, product.uom_po_id, round=False)
        taxes = product.supplier_taxes_id._filter_taxes_by_company(line.company_id)
        position = self.env['account.fiscal.position'].with_company(line.company_id)
        if line.supplier_id:
            position = position._get_fiscal_position(line.supplier_id)
        taxes = position.map_tax(taxes)
        return taxes.compute_all(price, currency=currency, quantity=purchase_qty,
                                 product=product, partner=line.supplier_id)['total_excluded']

    @api.depends('qty_final', 'qty_suggested', 'budget_adjusted', 'budget_allocated_qty')
    def _compute_was_edited(self):
        """Una reducción automática no es una edición del comprador."""
        super()._compute_was_edited()
        for line in self.filtered('budget_adjusted'):
            line.was_edited = float_compare(line.qty_final, line.budget_allocated_qty,
                precision_rounding=line.product_id.uom_id.rounding or .01) != 0
