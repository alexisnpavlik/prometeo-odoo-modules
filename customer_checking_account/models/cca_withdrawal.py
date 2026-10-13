# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("pending", "Pendiente"),
    ("partial", "Pago parcial"),
    ("paid", "Pagado"),
    ("cancel", "Cancelado"),
]

# Campos cuyo cambio en borrador obliga a regenerar las cuotas.
FINANCING_FIELDS = {
    "line_ids", "surcharge_percent", "installment_count", "first_due_date", "frequency", "date",
}


class CcaWithdrawal(models.Model):
    _name = "cca.withdrawal"
    _description = "Retiro de cliente"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="cca.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    partner_vat = fields.Char(related="partner_id.vat", string="DNI", store=True, index=True)
    account_balance = fields.Monetary(
        related="account_id.balance", string="Saldo actual", currency_field="currency_id"
    )
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today, tracking=True)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", string="Moneda", readonly=True)
    note = fields.Text(string="Notas")
    line_ids = fields.One2many("cca.withdrawal.line", "withdrawal_id", string="Líneas", copy=True)
    installment_ids = fields.One2many("cca.installment", "withdrawal_id", string="Cuotas")
    surcharge_percent = fields.Float(string="Recargo (%)", digits=(5, 2), tracking=True)
    installment_count = fields.Integer(string="Cuotas", default=1, required=True, tracking=True)
    first_due_date = fields.Date(
        string="Primer vencimiento",
        required=True,
        default=lambda self: fields.Date.context_today(self) + relativedelta(months=1),
        tracking=True,
    )
    frequency = fields.Selection(
        selection=[("monthly", "Mensual"), ("weekly", "Semanal")],
        string="Frecuencia",
        default="monthly",
        required=True,
    )
    amount_untaxed = fields.Monetary(
        string="Subtotal", compute="_compute_amounts", store=True, currency_field="currency_id"
    )
    amount_surcharge = fields.Monetary(
        string="Recargo", compute="_compute_amounts", store=True, currency_field="currency_id"
    )
    amount_total = fields.Monetary(
        string="Total", compute="_compute_amounts", store=True, currency_field="currency_id",
        tracking=True,
    )
    amount_residual = fields.Monetary(
        string="Saldo", compute="_compute_amount_residual", store=True, currency_field="currency_id"
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        compute="_compute_state",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        default="draft",
    )
    is_confirmed = fields.Boolean(copy=False, help="Bandera interna: se levanta al confirmar.")
    is_cancelled = fields.Boolean(copy=False, help="Bandera interna: el estado computado la respeta.")
    is_overdue = fields.Boolean(
        string="Vencido", compute="_compute_is_overdue", store=True, index=True
    )
    picking_id = fields.Many2one("stock.picking", string="Albarán", readonly=True, copy=False)
    return_picking_id = fields.Many2one(
        "stock.picking", string="Devolución", readonly=True, copy=False
    )

    @api.depends("line_ids.price_subtotal", "surcharge_percent")
    def _compute_amounts(self):
        """Subtotal de líneas, recargo sobre el subtotal y total."""
        for withdrawal in self:
            currency = withdrawal.currency_id or self.env.company.currency_id
            untaxed = sum(withdrawal.line_ids.mapped("price_subtotal"))
            surcharge = currency.round(untaxed * (withdrawal.surcharge_percent or 0.0) / 100.0)
            withdrawal.amount_untaxed = untaxed
            withdrawal.amount_surcharge = surcharge
            withdrawal.amount_total = untaxed + surcharge

    @api.depends("installment_ids.amount_residual", "is_confirmed", "is_cancelled")
    def _compute_amount_residual(self):
        """Saldo del retiro: residual de sus cuotas. En borrador no hay deuda."""
        for withdrawal in self:
            withdrawal.amount_residual = (
                sum(withdrawal.installment_ids.mapped("amount_residual"))
                if withdrawal.is_confirmed and not withdrawal.is_cancelled else 0.0
            )

    @api.depends("installment_ids.state", "is_confirmed", "is_cancelled")
    def _compute_is_overdue(self):
        """Vencido: confirmado y con al menos una cuota vencida."""
        for withdrawal in self:
            withdrawal.is_overdue = bool(
                withdrawal.is_confirmed and not withdrawal.is_cancelled
                and any(i.state == "overdue" for i in withdrawal.installment_ids)
            )

    @api.depends(
        "is_cancelled", "is_confirmed", "installment_ids.state",
        "installment_ids.amount_allocated", "installment_ids.amount_residual",
    )
    def _compute_state(self):
        """Deriva el estado de las banderas y de las cuotas. Nunca se escribe a mano."""
        for withdrawal in self:
            if withdrawal.is_cancelled:
                withdrawal.state = "cancel"
                continue
            if not withdrawal.is_confirmed:
                withdrawal.state = "draft"
                continue
            installments = withdrawal.installment_ids
            residual = sum(installments.mapped("amount_residual"))
            if installments and all(i.state == "paid" for i in installments) and \
                    withdrawal.currency_id.compare_amounts(residual, 0.0) == 0:
                withdrawal.state = "paid"
            elif any(i.amount_allocated > 0 for i in installments):
                withdrawal.state = "partial"
            else:
                withdrawal.state = "pending"

    @api.constrains("surcharge_percent", "installment_count")
    def _check_financing(self):
        """Recargo no negativo y al menos una cuota."""
        for withdrawal in self:
            if withdrawal.surcharge_percent < 0:
                raise ValidationError(_("El recargo no puede ser negativo."))
            if withdrawal.installment_count < 1:
                raise ValidationError(_("La cantidad de cuotas debe ser al menos 1."))

    def _cca_due_date(self, index):
        """Vencimiento de la cuota `index` (base 0) según la frecuencia."""
        self.ensure_one()
        step = relativedelta(weeks=index) if self.frequency == "weekly" else relativedelta(months=index)
        return self.first_due_date + step

    def _cca_installment_values(self):
        """Valores de las cuotas a partir del total. El resto del redondeo va a la última."""
        self.ensure_one()
        count = max(self.installment_count, 1)
        currency = self.currency_id or self.env.company.currency_id
        total = self.amount_total
        if currency.compare_amounts(total, 0.0) <= 0 or not self.first_due_date:
            return []
        base = currency.round(total / count)
        values, accumulated = [], 0.0
        for index in range(count):
            amount = currency.round(total - accumulated) if index == count - 1 else base
            accumulated += amount
            values.append({
                "sequence": index + 1,
                "date_due": self._cca_due_date(index),
                "amount": amount,
            })
        return values

    def _cca_regenerate_installments(self):
        """Borra y vuelve a crear las cuotas de retiros en borrador."""
        installment_model = self.env["cca.installment"].sudo()
        for withdrawal in self.filtered(lambda w: not w.is_confirmed and not w.is_cancelled):
            withdrawal.installment_ids.sudo().unlink()
            installment_model.create([
                dict(vals, withdrawal_id=withdrawal.id)
                for vals in withdrawal._cca_installment_values()
            ])
        return True

    @api.onchange("line_ids", "surcharge_percent", "installment_count", "first_due_date", "frequency")
    def _onchange_financing(self):
        """Vista previa de las cuotas mientras se carga el retiro."""
        if self.is_confirmed or self.is_cancelled:
            return
        commands = [fields.Command.clear()]
        commands += [fields.Command.create(vals) for vals in self._cca_installment_values()]
        self.installment_ids = commands

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """Precarga la cuenta del cliente (el cliente web valida required antes de create)."""
        if self.partner_id:
            company = self.company_id or self.env.company
            self.account_id = self.env["cca.account"].sudo()._get_or_create(self.partner_id, company)
        else:
            self.account_id = False

    def _cca_posted_allocations(self):
        """Imputaciones del retiro que provienen de pagos vigentes."""
        self.ensure_one()
        return self.installment_ids.mapped("allocation_ids").filtered(
            lambda a: a.payment_id.state == "posted"
        )

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna número, resuelve la cuenta del cliente y genera las cuotas de borrador."""
        account_model = self.env["cca.account"].sudo()
        for vals in vals_list:
            if not vals.get("account_id"):
                partner = self.env["res.partner"].browse(vals.get("partner_id"))
                company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
                vals["account_id"] = account_model._get_or_create(partner, company).id
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cca.withdrawal") or "/"
            # Las cuotas de la vista previa del onchange se descartan: se regeneran abajo.
            vals.pop("installment_ids", None)
        withdrawals = super().create(vals_list)
        withdrawals._cca_regenerate_installments()
        return withdrawals

    def write(self, vals):
        """Bloquea líneas fuera de borrador y resincroniza las cuotas en borrador."""
        if "line_ids" in vals and any(w.is_confirmed or w.is_cancelled for w in self):
            raise UserError(_("No se pueden modificar las líneas de un retiro confirmado o cancelado."))
        if FINANCING_FIELDS & set(vals) and any(w.is_confirmed for w in self):
            raise UserError(_("No se puede cambiar la financiación de un retiro confirmado."))
        if not any(w.is_confirmed for w in self):
            vals.pop("installment_ids", None)
        res = super().write(vals)
        if FINANCING_FIELDS & set(vals):
            self._cca_regenerate_installments()
        return res

    def unlink(self):
        """Solo se pueden borrar retiros en borrador o cancelados."""
        if any(w.state not in ("draft", "cancel") for w in self):
            raise UserError(_("Solo se pueden eliminar retiros en borrador o cancelados."))
        return super().unlink()

    def _cca_check_confirmable(self):
        """Precondiciones para confirmar: borrador, DNI, líneas y total positivo."""
        for withdrawal in self:
            if withdrawal.state != "draft":
                raise UserError(_("El retiro %s ya fue confirmado o cancelado.", withdrawal.name))
            if not withdrawal.partner_id.vat:
                raise UserError(_(
                    "Cargá el DNI de %s antes de confirmar el retiro.",
                    withdrawal.partner_id.display_name,
                ))
            if not withdrawal.line_ids:
                raise UserError(_("El retiro %s no tiene líneas.", withdrawal.name))
            if withdrawal.currency_id.compare_amounts(withdrawal.amount_total, 0.0) <= 0:
                raise UserError(_("El total del retiro %s debe ser mayor a cero.", withdrawal.name))

    def _cca_check_limit(self):
        """Saldo actual + total contra el límite. Devuelve el aviso en 'warn'; bloquea en 'block'."""
        self.ensure_one()
        account = self.account_id.sudo()
        if account.limit_mode == "none" or not account.credit_limit:
            return ""
        projected = account.balance + self.amount_total
        if self.currency_id.compare_amounts(projected, account.credit_limit) <= 0:
            return ""
        message = _(
            "El retiro deja a %(partner)s con un saldo de %(projected)s, por encima de su límite de %(limit)s.",
            partner=self.partner_id.display_name,
            projected=projected,
            limit=account.credit_limit,
        )
        if account.limit_mode == "block":
            raise UserError(_("%s\n\nSubí el límite en la cuenta del cliente y volvé a confirmar.", message))
        return message

    def _cca_picking_type(self):
        """Tipo de operación: el de la compañía o el de salidas del almacén principal."""
        self.ensure_one()
        if self.company_id.cca_picking_type_id:
            return self.company_id.cca_picking_type_id
        warehouse = self.env["stock.warehouse"].sudo().search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_("No hay un almacén configurado en la compañía %s.", self.company_id.name))
        return warehouse.out_type_id

    def _cca_storable_lines(self):
        """Líneas con mercadería física. Mira `type` además de `is_storable` (ver gotcha en tests)."""
        return self.line_ids.filtered(
            lambda l: l.product_id.type == "consu" and l.product_id.is_storable
        )

    def _cca_validate_picking(self, picking):
        """Valida un albarán sin diálogos: sin SMS, sin backorder, cantidades = demanda."""
        picking = picking.sudo().with_context(skip_sms=True, skip_backorder=True)
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.move_ids.picked = True
        result = picking.button_validate()
        if isinstance(result, dict) and result.get("res_model"):
            wizard_model = self.env[result["res_model"]].sudo().with_context(**(result.get("context") or {}))
            wizard = wizard_model.browse(result["res_id"]) if result.get("res_id") else wizard_model.create({})
            for method in ("process_cancel_backorder", "process"):
                if hasattr(wizard, method):
                    getattr(wizard, method)()
                    break
        if picking.state != "done":
            raise UserError(_(
                "No se pudo validar el albarán %(picking)s: quedó en estado '%(state)s'. Validalo desde Inventario.",
                picking=picking.name,
                state=picking.state,
            ))
        return True

    def _cca_create_and_validate_picking(self):
        """Crea el albarán de salida de las líneas almacenables y lo valida."""
        self.ensure_one()
        lines = self._cca_storable_lines()
        if not lines:
            _logger.info("Retiro %s sin productos almacenables: no genera albarán", self.name)
            return False
        picking_type = self._cca_picking_type()
        picking = self.env["stock.picking"].sudo().create({
            "partner_id": self.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "scheduled_date": fields.Datetime.to_datetime(self.date),
            "origin": self.name,
            "company_id": self.company_id.id,
            "move_ids": [fields.Command.create({
                "name": line.name or line.product_id.display_name,
                "product_id": line.product_id.id,
                "product_uom_qty": line.quantity,
                "product_uom": line.product_id.uom_id.id,
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "company_id": self.company_id.id,
            }) for line in lines],
        })
        picking.action_confirm()
        self._cca_validate_picking(picking)
        self.picking_id = picking.id
        return picking

    def _cca_return_picking(self):
        """Genera y valida la devolución del albarán del retiro."""
        self.ensure_one()
        picking = self.picking_id.sudo()
        wizard = self.env["stock.return.picking"].sudo().with_context(
            active_id=picking.id, active_ids=picking.ids, active_model="stock.picking"
        ).create({"picking_id": picking.id})
        for return_line in wizard.product_return_moves:
            return_line.quantity = return_line.move_id.quantity
        action = wizard.action_create_returns()
        return_picking = self.env["stock.picking"].sudo().browse(action["res_id"])
        self._cca_validate_picking(return_picking)
        self.return_picking_id = return_picking.id
        return return_picking

    def _cca_after_confirm(self):
        """Hook post-confirmación. Task 5 lo usa para imputar saldo a favor."""
        return True

    def action_confirm(self):
        """Confirma en un paso: valida, controla el límite, descuenta stock y congela las cuotas."""
        self._cca_check_confirmable()
        warnings = []
        for withdrawal in self:
            warning = withdrawal._cca_check_limit()
            withdrawal._cca_regenerate_installments()
            withdrawal._cca_create_and_validate_picking()
            withdrawal.is_confirmed = True
            withdrawal._cca_after_confirm()
            withdrawal._message_log(body=_("Retiro confirmado por %s.", self.env.user.display_name))
            if warning:
                withdrawal._message_log(body=warning)
                warnings.append(warning)
        if warnings:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Límite de crédito superado"),
                    "message": "\n".join(warnings),
                    "type": "warning",
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return True

    def action_cancel(self):
        """Cancela: exige que no haya pagos imputados y devuelve el stock."""
        for withdrawal in self:
            if withdrawal.is_cancelled:
                raise UserError(_("El retiro %s ya está cancelado.", withdrawal.name))
            allocations = withdrawal._cca_posted_allocations()
            if allocations:
                raise UserError(_(
                    "El retiro %(name)s tiene pagos imputados por %(amount)s. Anulá esos pagos primero.",
                    name=withdrawal.name,
                    amount=sum(allocations.mapped("amount")),
                ))
            if withdrawal.picking_id and withdrawal.picking_id.state == "done":
                withdrawal._cca_return_picking()
            withdrawal.installment_ids.sudo().unlink()
            withdrawal.is_cancelled = True
            withdrawal._message_log(body=_("Retiro cancelado por %s.", self.env.user.display_name))
        return True

    def action_draft(self):
        """Reabre un retiro cancelado para corregirlo."""
        for withdrawal in self:
            if not withdrawal.is_cancelled:
                raise UserError(_("Solo se puede volver a borrador un retiro cancelado."))
            withdrawal.write({
                "is_cancelled": False,
                "is_confirmed": False,
                "picking_id": False,
                "return_picking_id": False,
            })
            withdrawal._cca_regenerate_installments()
        return True

    def action_view_picking(self):
        """Abre el albarán del retiro."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Albarán de %s", self.name),
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
            "view_mode": "form",
        }
