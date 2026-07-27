# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("draft", "Borrador"),
    ("pending", "Pendiente"),
    ("partial", "Pago parcial"),
    ("paid", "Pagado"),
    ("cancel", "Cancelado"),
]


class CawWithdrawal(models.Model):
    _name = "caw.withdrawal"
    _description = "Retiro de mercadería a cuenta corriente"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(
        string="Número",
        required=True,
        copy=False,
        readonly=True,
        default="/",
    )
    account_id = fields.Many2one(
        comodel_name="caw.account",
        string="Cuenta corriente",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contacto",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        domain="[('caw_enabled', '=', True)]",
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Responsable",
        default=lambda self: self.env.user,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Moneda",
        readonly=True,
    )
    note = fields.Text(string="Notas")
    line_ids = fields.One2many(
        comodel_name="caw.withdrawal.line",
        inverse_name="withdrawal_id",
        string="Líneas",
    )
    installment_ids = fields.One2many(
        comodel_name="caw.installment",
        inverse_name="withdrawal_id",
        string="Cuotas",
    )
    amount_total = fields.Monetary(
        string="Total",
        compute="_compute_amount_total",
        store=True,
        currency_field="currency_id",
        tracking=True,
    )
    state = fields.Selection(
        selection=STATE_SELECTION,
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        """Total del retiro: suma de los subtotales de sus líneas."""
        for withdrawal in self:
            withdrawal.amount_total = sum(withdrawal.line_ids.mapped("price_subtotal"))

    @api.model_create_multi
    def create(self, vals_list):
        """Asigna número de secuencia y resuelve la cuenta corriente del contacto."""
        for vals in vals_list:
            if not vals.get("account_id"):
                vals["account_id"] = self._caw_resolve_account(vals).id
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("caw.withdrawal") or "/"
        return super().create(vals_list)

    @api.model
    def _caw_resolve_account(self, vals):
        """Devuelve la cuenta corriente del contacto, validando que esté habilitado."""
        partner = self.env["res.partner"].browse(vals.get("partner_id"))
        company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
        if not partner or not partner.caw_enabled:
            raise UserError(_(
                "El contacto %s no está habilitado para cuenta corriente.",
                partner.display_name or "",
            ))
        return self.env["caw.account"].sudo()._get_or_create(partner, company)

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        """Restringe el selector de contactos a los habilitados."""
        if self.partner_id and not self.partner_id.caw_enabled:
            self.partner_id = False
            return {"warning": {
                "title": _("Contacto no habilitado"),
                "message": _("Ese contacto no está habilitado para cuenta corriente."),
            }}

    def unlink(self):
        """Solo se pueden borrar retiros en borrador o cancelados."""
        if any(w.state not in ("draft", "cancel") for w in self):
            raise UserError(_("Solo se pueden eliminar retiros en borrador o cancelados."))
        return super().unlink()

    def write(self, vals):
        """Impide editar las líneas de un retiro que ya salió de borrador."""
        if "line_ids" in vals and any(w.state not in ("draft",) for w in self):
            raise UserError(_("No se pueden modificar las líneas de un retiro confirmado."))
        return super().write(vals)

    def _caw_due_date(self, index, first_days, period, cutoff_day):
        """Calcula el vencimiento de la cuota `index` (base 0) del retiro."""
        due = self.date + relativedelta(days=first_days)
        if period == "days":
            due += relativedelta(days=first_days * index)
        elif period == "weeks":
            due += relativedelta(weeks=index)
        else:
            due += relativedelta(months=index)
        if cutoff_day:
            due += relativedelta(day=min(cutoff_day, 28))
        return due

    def _caw_build_installment_values(self, count, first_days, period, cutoff_day):
        """Arma los valores de las cuotas. El resto del redondeo va a la última."""
        self.ensure_one()
        if count < 1:
            raise UserError(_("La cantidad de cuotas debe ser al menos 1."))
        currency = self.currency_id
        base = currency.round(self.amount_total / count)
        values = []
        accumulated = 0.0
        for index in range(count):
            is_last = index == count - 1
            amount = currency.round(self.amount_total - accumulated) if is_last else base
            accumulated += amount
            values.append({
                "withdrawal_id": self.id,
                "sequence": index + 1,
                "date_due": self._caw_due_date(index, first_days, period, cutoff_day),
                "amount": amount,
            })
        return values

    def _caw_generate_installments(self, count, first_days, period, cutoff_day):
        """Borra las cuotas existentes y genera el plan indicado."""
        for withdrawal in self:
            withdrawal.installment_ids.unlink()
            values = withdrawal._caw_build_installment_values(count, first_days, period, cutoff_day)
            self.env["caw.installment"].sudo().create(values)
            _logger.info("Retiro %s: generadas %s cuotas", withdrawal.name, count)
        return True

    def _caw_check_confirmable(self):
        """Valida las precondiciones para confirmar un retiro."""
        for withdrawal in self:
            if withdrawal.state != "draft":
                raise UserError(_("El retiro %s ya fue confirmado.", withdrawal.name))
            if not withdrawal.partner_id.caw_enabled:
                raise UserError(_(
                    "El contacto %s no está habilitado para cuenta corriente.",
                    withdrawal.partner_id.display_name,
                ))
            if not withdrawal.line_ids:
                raise UserError(_("El retiro %s no tiene líneas.", withdrawal.name))
            if withdrawal.currency_id.compare_amounts(withdrawal.amount_total, 0.0) <= 0:
                raise UserError(_("El total del retiro %s debe ser mayor a cero.", withdrawal.name))

    def action_confirm(self):
        """Confirma el retiro generando las cuotas con los defaults de la compañía."""
        self._caw_check_confirmable()
        for withdrawal in self:
            company = withdrawal.company_id
            withdrawal._caw_generate_installments(
                count=company.caw_installment_count or 1,
                first_days=company.caw_installment_days or 30,
                period=company.caw_installment_period or "months",
                cutoff_day=company.caw_cutoff_day or 0,
            )
            withdrawal.state = "pending"
            withdrawal.message_post(body=_("Retiro confirmado por %s.", self.env.user.display_name))
        return True
