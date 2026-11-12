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
    date = fields.Date(
        string="Fecha", required=True, default=fields.Date.context_today, index=True, tracking=True
    )
    amount = fields.Monetary(string="Monto", required=True, currency_field="currency_id", tracking=True)
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
        tracking=True,
    )
    ref = fields.Char(string="Referencia", tracking=True)
    state = fields.Selection(
        selection=[("posted", "Registrado"), ("cancel", "Anulado")],
        string="Estado",
        default="posted",
        required=True,
        copy=False,
        index=True,
        tracking=True,
    )
    is_down_payment = fields.Boolean(
        string="Es entrega inicial",
        compute="_compute_is_down_payment",
        help="El monto y el cliente de la entrega se cambian editando el retiro.",
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
    multi_installment_warning = fields.Html(
        string="Advertencia de varias cuotas",
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

    def _compute_is_down_payment(self):
        """Marca los pagos que son la entrega inicial de algún retiro."""
        down_ids = set(self.env["cca.withdrawal"].sudo().search(
            [("down_payment_id", "in", self.ids)]
        ).mapped("down_payment_id").ids)
        for payment in self:
            payment.is_down_payment = payment.id in down_ids

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
            payment.multi_installment_warning = False
            if payment._origin.id or not payment.account_id:
                payment.allocation_preview = False
                continue
            payment.allocation_preview = payment._cca_render_preview()
            payment.multi_installment_warning = payment._cca_render_multi_warning()

    def _cca_render_multi_warning(self):
        """Aviso cuando el monto cubre más de una cuota: evita cobrar el total por error."""
        self.ensure_one()
        account = self.account_id._origin or self.account_id
        plan, _rest = account._cca_fifo_plan(self.amount)
        if len(plan) <= 1:
            return False
        money = lambda value: escape(formatLang(self.env, value, currency_obj=self.currency_id))
        first = plan[0][0]
        return Markup(
            "<div class='alert alert-warning mb-0' role='alert'><strong>%s</strong> %s</div>"
        ) % (
            _("Este pago cubre %s cuotas.", len(plan)),
            _("Si el cliente quiere pagar solo la próxima cuota (%(label)s), el monto es %(amount)s.",
              label=first.label, amount=money(first.amount_residual)),
        )

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
            for payment in payments:
                payment._cca_log_on_withdrawals(
                    payment.allocation_ids.mapped("withdrawal_id"),
                    _("Pago %(name)s registrado por %(user)s: %(amount)s.",
                      name=payment.name, user=self.env.user.display_name,
                      amount=payment._cca_money(payment.amount)),
                )
        return payments

    def _cca_money(self, value):
        """Monto formateado en la moneda del pago."""
        self.ensure_one()
        return formatLang(self.env, value, currency_obj=self.currency_id)

    def _cca_display_value(self, field, value):
        """Valor legible de un campo editable, para el historial."""
        if field == "amount":
            return self._cca_money(value or 0.0)
        if field == "partner_id":
            return self.env["res.partner"].browse(value).display_name if isinstance(value, int) else value.display_name
        if field == "date":
            return fields.Date.to_date(value).strftime("%d/%m/%Y") if value else ""
        if field == "payment_method":
            return dict(self._fields["payment_method"].selection).get(value, value or "")
        return value or "—"

    def _cca_changes(self, vals):
        """Lista 'Campo: antes → después' de los campos editables que cambian."""
        self.ensure_one()
        changes = []
        for field in ("partner_id", "date", "payment_method", "amount", "ref"):
            if field not in vals:
                continue
            old = self[field]
            new = vals[field]
            if field == "partner_id":
                old = old.id
            elif field == "date":
                new = fields.Date.to_date(new)
            elif field == "ref":
                old, new = old or False, new or False
            if old == new or (field == "amount" and self.currency_id.compare_amounts(old, new or 0.0) == 0):
                continue
            changes.append("%s: %s → %s" % (
                self._fields[field].string,
                self._cca_display_value(field, self[field]),
                self._cca_display_value(field, vals[field]),
            ))
        return changes

    def _cca_log_on_withdrawals(self, withdrawals, body):
        """Deja constancia del movimiento del pago en el historial de cada retiro afectado."""
        for withdrawal in withdrawals.sudo():
            withdrawal._message_log(body=body)

    def write(self, vals):
        """Permite corregir un pago registrado.

        Si cambia el monto o el cliente, se deshacen sus imputaciones y se vuelven a hacer
        por FIFO; lo que quede liberado lo cubre el saldo a favor de otros pagos.
        """
        realloc_fields = {"amount", "partner_id"}
        edit_fields = realloc_fields | {"date", "payment_method", "ref"}
        if self.env.context.get("cca_payment_internal_write") or not edit_fields & set(vals):
            return super().write(vals)
        if (edit_fields - {"ref"}) & set(vals) and any(p.state == "cancel" for p in self):
            raise UserError(_("Un pago anulado no se puede editar."))
        changes = {payment.id: payment._cca_changes(vals) for payment in self}
        withdrawals_before = {payment.id: payment.allocation_ids.mapped("withdrawal_id") for payment in self}
        realloc = self.filtered(
            lambda p: any(
                (p[field].id if field == "partner_id" else p[field]) != vals[field]
                for field in realloc_fields & set(vals)
            )
        ) if realloc_fields & set(vals) else self.browse()
        if realloc.filtered("is_down_payment"):
            raise UserError(_(
                "El monto y el cliente de una entrega inicial se cambian editando el retiro."
            ))
        old_accounts = realloc.mapped("account_id")
        realloc.allocation_ids.sudo().unlink()
        if vals.get("partner_id"):
            partner = self.env["res.partner"].browse(vals["partner_id"])
            accounts = {
                company: self.env["cca.account"].sudo()._get_or_create(partner, company)
                for company in self.mapped("company_id")
            }
            for payment in self:
                super(CcaPayment, payment).write(dict(vals, account_id=accounts[payment.company_id].id))
        else:
            super().write(vals)
        if realloc:
            (old_accounts | realloc.mapped("account_id"))._cca_apply_credit()
            for payment in realloc:
                payment._message_log(body=_(
                    "Pago editado por %s: imputaciones recalculadas.", self.env.user.display_name
                ))
        for payment in self:
            if not changes[payment.id]:
                continue
            payment._cca_log_on_withdrawals(
                withdrawals_before[payment.id] | payment.allocation_ids.mapped("withdrawal_id"),
                _("Pago %(name)s editado por %(user)s. %(changes)s.",
                  name=payment.name, user=self.env.user.display_name,
                  changes="; ".join(changes[payment.id])),
            )
        return True

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
            if payment.is_down_payment:
                raise UserError(_(
                    "El pago %s es la entrega inicial: se deshace devolviendo o editando el retiro.",
                    payment.name,
                ))
            withdrawals = payment.allocation_ids.mapped("withdrawal_id")
            payment.allocation_ids.sudo().unlink()
            payment.state = "cancel"
            payment._message_log(body=_("Pago anulado por %s.", self.env.user.display_name))
            payment._cca_log_on_withdrawals(withdrawals, _(
                "Pago %(name)s de %(amount)s anulado por %(user)s: las cuotas que cubría vuelven a quedar pendientes.",
                name=payment.name, amount=payment._cca_money(payment.amount),
                user=self.env.user.display_name,
            ))
        # Las cuotas que liberó la anulación las cubre el saldo a favor de otros pagos.
        self.mapped("account_id")._cca_apply_credit()
        return True

    def action_open(self):
        """Abre el pago en un diálogo para corregirlo."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "cca.payment",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

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
