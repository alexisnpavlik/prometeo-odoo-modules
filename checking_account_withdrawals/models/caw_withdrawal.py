# -*- coding: utf-8 -*-
import logging

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
