# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.tools.misc import formatLang
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class CcaPayment(models.Model):
    _name = "cca.payment"
    _description = "Pago de cliente"
    _inherit = ["mail.thread"]
    _order = "date desc, name desc, id desc"

    name = fields.Char(string="Número", required=True, copy=False, readonly=True, default="/")
    account_id = fields.Many2one(
        comodel_name="cca.account",
        string="Cuenta corriente",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
        help="Se resuelve sola a partir del cliente y la compañía.",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente",
        required=True,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Compañía",
        required=True,
        readonly=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    date = fields.Date(string="Fecha", required=True, default=fields.Date.context_today, index=True)
    amount = fields.Monetary(string="Monto", required=True, currency_field="currency_id")
    payment_method = fields.Selection(
        selection=[
            ("cash", "Efectivo"),
            ("transfer", "Transferencia"),
            ("card", "Tarjeta"),
            ("other", "Otro"),
        ],
        string="Medio de pago",
        default="cash",
        required=True,
    )
    ref = fields.Char(string="Referencia")
    state = fields.Selection(
        selection=[("posted", "Registrado"), ("cancel", "Anulado")],
        string="Estado",
        default="posted",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    allocation_ids = fields.One2many("cca.allocation", "payment_id", string="Imputaciones")
    account_balance = fields.Monetary(
        related="account_id.balance", string="Deuda total", currency_field="currency_id"
    )
    account_overdue_balance = fields.Monetary(
        related="account_id.overdue_balance", string="Vencido", currency_field="currency_id"
    )
    account_credit_balance = fields.Monetary(
        related="account_id.credit_balance", string="Saldo a favor previo", currency_field="currency_id"
    )
    allocation_preview = fields.Html(
        string="Qué cubre este pago",
        compute="_compute_allocation_preview",
        sanitize=False,
    )
    amount_allocated = fields.Monetary(
        string="Imputado", compute="_compute_allocated", store=True, currency_field="currency_id"
    )
    amount_unallocated = fields.Monetary(
        string="Saldo a favor", compute="_compute_allocated", store=True, currency_field="currency_id"
    )

    @api.depends("amount", "allocation_ids.amount", "state")
    def _compute_allocated(self):
        """Imputado y remanente. Un pago anulado no deja saldo a favor."""
        for payment in self:
            allocated = sum(payment.allocation_ids.mapped("amount"))
            payment.amount_allocated = allocated
            payment.amount_unallocated = (
                max(payment.amount - allocated, 0.0) if payment.state == "posted" else 0.0
            )

    @api.onchange("partner_id", "company_id")
    def _onchange_partner_id(self):
        """Resuelve la cuenta del cliente para mostrar su deuda antes de guardar."""
        if self.partner_id:
            self.account_id = self.env["cca.account"].sudo()._get_or_create(
                self.partner_id, self.company_id or self.env.company
            )
        else:
            self.account_id = False

    @api.depends("account_id", "amount", "state")
    def _compute_allocation_preview(self):
        """Tabla con las cuotas que cubriría el pago. Solo para pagos sin guardar."""
        for payment in self:
            if payment._origin.id or not payment.account_id:
                payment.allocation_preview = False
                continue
            payment.allocation_preview = payment._cca_render_preview()

    def _cca_render_preview(self):
        """Arma el HTML de la vista previa a partir del mismo reparto FIFO que se imputa."""
        self.ensure_one()
        currency = self.currency_id
        money = lambda value: escape(formatLang(self.env, value, currency_obj=currency))
        account = self.account_id._origin or self.account_id
        if not account._cca_open_installments():
            return Markup('<p class="text-muted">El cliente no tiene cuotas pendientes.</p>')
        plan, rest = account._cca_fifo_plan(self.amount)
        covered = dict((inst.id, amount) for inst, amount in plan)
        rows = []
        for installment in account._cca_open_installments():
            portion = covered.get(installment.id, 0.0)
            left = installment.amount_residual - portion
            if not portion:
                status, css = _("Sigue pendiente"), "text-muted"
            elif currency.is_zero(left):
                status, css = _("Queda pagada"), "text-success fw-bold"
            else:
                status, css = _("Pago parcial"), "text-warning fw-bold"
            overdue = installment.date_due < fields.Date.context_today(self)
            rows.append(Markup(
                "<tr><td>%s</td><td>%s</td><td class='%s'>%s</td><td class='text-end'>%s</td>"
                "<td class='text-end fw-bold'>%s</td><td class='text-end'>%s</td><td class='%s'>%s</td></tr>"
            ) % (
                installment.withdrawal_id.name,
                installment.label,
                "text-danger" if overdue else "", installment.date_due.strftime("%d/%m/%Y"),
                money(installment.amount_residual), money(portion) if portion else "—",
                money(left), css, status,
            ))
        html = Markup(
            "<table class='table table-sm o_cca_preview'><thead><tr>"
            "<th>Retiro</th><th>Cuota</th><th>Vence</th><th class='text-end'>Debe</th>"
            "<th class='text-end'>Este pago</th><th class='text-end'>Queda</th><th>Estado</th>"
            "</tr></thead><tbody>%s</tbody></table>"
        ) % Markup("").join(rows)
        if not currency.is_zero(rest):
            html += Markup("<div class='alert alert-info mb-0'>%s</div>") % _(
                "Sobran %s: quedan como saldo a favor y se descuentan del próximo retiro.", money(rest)
            )
        return html

    @api.constrains("amount")
    def _check_amount(self):
        """El monto debe ser mayor a cero."""
        for payment in self:
            if payment.currency_id.compare_amounts(payment.amount, 0.0) <= 0:
                raise ValidationError(_("El monto del pago debe ser mayor a cero."))

    @api.model_create_multi
    def create(self, vals_list):
        """Numera el pago y lo imputa por FIFO en el acto."""
        account_model = self.env["cca.account"].sudo()
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("cca.payment") or "/"
            if vals.get("account_id") and not vals.get("partner_id"):
                account = account_model.browse(vals["account_id"])
                vals.update(partner_id=account.partner_id.id, company_id=account.company_id.id)
            elif vals.get("partner_id"):
                partner = self.env["res.partner"].browse(vals["partner_id"])
                company = self.env["res.company"].browse(vals.get("company_id")) or self.env.company
                vals["company_id"] = company.id
                vals["account_id"] = account_model._get_or_create(partner, company).id
        payments = super().create(vals_list)
        if not self.env.context.get("cca_no_auto_allocate"):
            payments._cca_allocate_fifo()
        return payments

    def _cca_allocate_fifo(self):
        """Imputa el remanente de cada pago vigente según el reparto FIFO de la cuenta."""
        allocation_model = self.env["cca.allocation"].sudo()
        for payment in self.filtered(lambda p: p.state == "posted"):
            plan, rest = payment.account_id._cca_fifo_plan(payment.amount - payment.amount_allocated)
            allocation_model.create([
                {"payment_id": payment.id, "installment_id": installment.id, "amount": amount}
                for installment, amount in plan
            ])
            if not payment.currency_id.is_zero(rest):
                _logger.info("Pago %s: %s queda como saldo a favor", payment.name, rest)
        return True

    @api.model
    def _cca_new_payment_action(self, partner, amount):
        """Acción de pago nuevo en diálogo, con cliente y monto sugerido."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Registrar pago de %s", partner.display_name),
            "res_model": "cca.payment",
            "view_mode": "form",
            "target": "new",
            "context": {"default_partner_id": partner.id, "default_amount": amount},
        }

    def action_cancel(self):
        """Anula el pago y deshace sus imputaciones."""
        for payment in self:
            if payment.state == "cancel":
                raise UserError(_("El pago %s ya está anulado.", payment.name))
            payment.allocation_ids.sudo().unlink()
            payment.state = "cancel"
            payment._message_log(body=_("Pago anulado por %s.", self.env.user.display_name))
        # Las cuotas que liberó la anulación las cubre el saldo a favor de otros pagos.
        self.mapped("account_id")._cca_apply_credit()
        return True

    def action_print_receipt(self):
        """Comprobante de pago en PDF para entregar al cliente.

        config=False: el comprobante usa un layout propio, así que no hace falta que la
        compañía tenga configurado el diseño de documentos (si no, Odoo abre ese asistente).
        """
        return self.env.ref(
            "customer_checking_account.action_report_cca_payment_receipt"
        ).report_action(self, config=False)

    def _cca_receipt_lines(self):
        """Filas del comprobante: retiro, cuota n/N, monto aplicado y saldo que le queda."""
        self.ensure_one()
        return [{
            "withdrawal": allocation.withdrawal_id.name,
            "installment": allocation.installment_id.label,
            "date_due": allocation.installment_id.date_due,
            "amount": allocation.amount,
            "residual": allocation.installment_id.amount_residual,
        } for allocation in self.allocation_ids.sorted(
            lambda a: (a.installment_id.date_due, a.withdrawal_id.id, a.installment_id.sequence)
        )]
