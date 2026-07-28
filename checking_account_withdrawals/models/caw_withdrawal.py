# -*- coding: utf-8 -*-
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

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
        compute="_compute_state",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        default="draft",
    )
    is_cancelled = fields.Boolean(
        string="Cancelado",
        default=False,
        copy=False,
        help="Bandera interna: el estado computado la respeta para no pisar la cancelación.",
    )
    is_confirmed = fields.Boolean(
        string="Confirmado",
        default=False,
        copy=False,
        help="Bandera interna: pasa a True al confirmar y saca al retiro de borrador.",
    )
    amount_residual = fields.Monetary(
        string="Residual",
        compute="_compute_amount_residual",
        store=True,
        currency_field="currency_id",
    )
    is_overdue = fields.Boolean(
        string="En mora",
        compute="_compute_is_overdue",
        store=True,
        index=True,
        help="Indicador independiente del estado: el retiro tiene al menos una cuota vencida.",
    )
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Albarán",
        readonly=True,
        copy=False,
        index=True,
    )
    picking_state = fields.Selection(
        related="picking_id.state",
        string="Estado del albarán",
        store=True,
    )
    is_inconsistent = fields.Boolean(
        string="Inconsistente",
        compute="_compute_is_inconsistent",
        store=True,
        help="El albarán fue cancelado pero el retiro sigue vivo. Requiere revisión del Manager.",
    )

    @api.depends("line_ids.price_subtotal")
    def _compute_amount_total(self):
        """Total del retiro: suma de los subtotales de sus líneas."""
        for withdrawal in self:
            withdrawal.amount_total = sum(withdrawal.line_ids.mapped("price_subtotal"))

    @api.depends("installment_ids.amount_residual")
    def _compute_amount_residual(self):
        """Residual del retiro: suma de los residuales de sus cuotas."""
        for withdrawal in self:
            withdrawal.amount_residual = sum(withdrawal.installment_ids.mapped("amount_residual"))

    @api.depends("installment_ids.state")
    def _compute_is_overdue(self):
        """Mora: al menos una cuota vencida. No altera el estado de pago."""
        for withdrawal in self:
            withdrawal.is_overdue = any(
                installment.state == "overdue" for installment in withdrawal.installment_ids
            )

    @api.depends("picking_state", "is_cancelled")
    def _compute_is_inconsistent(self):
        """Señala los retiros vivos cuyo albarán fue cancelado."""
        for withdrawal in self:
            withdrawal.is_inconsistent = bool(
                withdrawal.picking_state == "cancel" and not withdrawal.is_cancelled
            )

    @api.depends(
        "is_cancelled",
        "is_confirmed",
        "amount_total",
        "installment_ids.state",
        "installment_ids.amount_allocated",
        "installment_ids.amount_residual",
    )
    def _compute_state(self):
        """Deriva el estado del retiro del estado de sus cuotas. Nunca se escribe a mano.

        pending: ninguna cuota con imputación.
        partial: al menos una cuota con imputación y residual total > 0.
        paid:    TODAS las cuotas pagadas y residual del retiro en cero.
        """
        for withdrawal in self:
            if withdrawal.is_cancelled:
                withdrawal.state = "cancel"
                continue
            if not withdrawal.is_confirmed:
                withdrawal.state = "draft"
                continue
            installments = withdrawal.installment_ids
            currency = withdrawal.currency_id
            residual = sum(installments.mapped("amount_residual"))
            all_paid = bool(installments) and all(i.state == "paid" for i in installments)
            if all_paid and currency.compare_amounts(residual, 0.0) == 0:
                withdrawal.state = "paid"
            elif any(i.amount_allocated > 0 for i in installments):
                withdrawal.state = "partial"
            else:
                withdrawal.state = "pending"

    @api.constrains("state", "installment_ids", "amount_residual")
    def _check_no_false_paid(self):
        """Blindaje de CC-31: rechaza 'paid' si alguna cuota tiene residual > 0."""
        for withdrawal in self:
            if withdrawal.state != "paid":
                continue
            open_installments = withdrawal.installment_ids.filtered(
                lambda i: i.currency_id.compare_amounts(i.amount_residual, 0.0) > 0
            )
            if open_installments:
                raise ValidationError(_(
                    "El retiro %(name)s no puede figurar como pagado: tiene %(count)s cuota(s) "
                    "con saldo pendiente.",
                    name=withdrawal.name,
                    count=len(open_installments),
                ))

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
        if "line_ids" in vals and any(w.is_confirmed or w.is_cancelled for w in self):
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
            if due < self.date:
                # El día de corte cayó antes de la fecha del retiro (p.ej. corte día 1
                # sobre un retiro del día 5): correr al corte del mes siguiente.
                due += relativedelta(months=1)
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
        """Borra las cuotas existentes y genera el plan indicado.

        Generar el plan de cuotas es lo que saca al retiro de borrador, por eso
        también levanta la bandera `is_confirmed` (el estado computado la respeta).
        """
        for withdrawal in self:
            withdrawal.installment_ids.unlink()
            values = withdrawal._caw_build_installment_values(count, first_days, period, cutoff_day)
            self.env["caw.installment"].sudo().create(values)
            withdrawal.is_confirmed = True
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

    def _caw_picking_type(self):
        """Tipo de operación del albarán: el de la compañía o el de salidas del almacén."""
        self.ensure_one()
        picking_type = self.company_id.caw_picking_type_id
        if picking_type:
            return picking_type
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1
        )
        if not warehouse:
            raise UserError(_(
                "No hay un almacén configurado en la compañía %s.", self.company_id.name
            ))
        return warehouse.out_type_id

    def _caw_picking_values(self, picking_type):
        """Valores de cabecera del albarán de salida del retiro."""
        self.ensure_one()
        return {
            "partner_id": self.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "scheduled_date": fields.Datetime.to_datetime(self.date),
            "origin": self.name,
            "company_id": self.company_id.id,
        }

    def _caw_move_values(self, line, picking):
        """Valores del movimiento de stock de una línea del retiro."""
        return {
            "picking_id": picking.id,
            "name": line.name or line.product_id.display_name,
            "product_id": line.product_id.id,
            "product_uom_qty": line.quantity,
            "product_uom": line.product_id.uom_id.id,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "company_id": self.company_id.id,
        }

    def _caw_create_picking(self):
        """Crea el albarán de salida del retiro. Usa sudo: el Operador no es de stock."""
        picking_model = self.env["stock.picking"].sudo()
        move_model = self.env["stock.move"].sudo()
        for withdrawal in self.filtered(lambda w: not w.picking_id):
            storable_lines = withdrawal.line_ids.filtered(
                lambda l: l.product_id.is_storable
            )
            if not storable_lines:
                _logger.info("Retiro %s sin productos almacenables: no genera albarán", withdrawal.name)
                continue
            picking_type = withdrawal._caw_picking_type()
            picking = picking_model.create(withdrawal._caw_picking_values(picking_type))
            move_model.create([
                withdrawal._caw_move_values(line, picking) for line in storable_lines
            ])
            picking.action_confirm()
            withdrawal.picking_id = picking.id
            _logger.info("Retiro %s: albarán %s generado", withdrawal.name, picking.name)
        return True

    def action_view_picking(self):
        """Abre el albarán asociado al retiro.

        No usa sudo: el Operador (group_cc_user) tiene acceso de solo lectura granular
        a stock.picking/stock.move/stock.move.line vía ir.model.access.csv, sin implicar
        stock.group_stock_user (eso reactivaría reglas de stock que el módulo no quiere dar).
        """
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_("El retiro %s no tiene albarán asociado.", self.name))
        return {
            "type": "ir.actions.act_window",
            "name": _("Albarán del retiro %s", self.name),
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
            "view_mode": "form",
        }

    def action_validate_picking(self):
        """Valida el albarán de salida del retiro (descuenta el stock).

        Usa sudo porque el Operador (group_cc_user) no tiene stock.group_stock_user.
        Este módulo no maneja entregas parciales: si Odoo devuelve el wizard intermedio
        de backorder (picking con cantidad hecha menor a la demandada), se resuelve
        automáticamente eligiendo "sin entrega parcial" para no dejar el flujo a mitad
        de camino esperando una acción manual que este módulo no expone.
        """
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_("El retiro %s no tiene albarán asociado.", self.name))
        if self.picking_id.state == "done":
            raise UserError(_("El albarán del retiro %s ya está validado.", self.name))
        picking = self.picking_id.sudo()
        result = picking.button_validate()
        if isinstance(result, dict) and result.get("res_model"):
            wizard = (
                self.env[result["res_model"]]
                .sudo()
                .with_context(**(result.get("context") or {}))
                .create({})
            )
            if hasattr(wizard, "process_cancel_backorder"):
                wizard.process_cancel_backorder()
            elif hasattr(wizard, "process"):
                wizard.process()
        return True

    def action_confirm(self):
        """Confirma el retiro generando las cuotas con los defaults de la compañía."""
        self._caw_check_confirmable()
        for withdrawal in self:
            force = bool(self.env.context.get("caw_force_limit"))
            warning = withdrawal._caw_check_limit(force=force)
            if warning:
                withdrawal.message_post(body=_(
                    "Retiro confirmado por encima del límite de crédito%(forced)s: %(warning)s",
                    forced=_(" (forzado por el Manager)") if force else "",
                    warning=warning,
                ))
            company = withdrawal.company_id
            plan = self.env.context.get("caw_plan")
            if plan:
                count, first_days, period, cutoff_day = plan
            else:
                count = company.caw_installment_count or 1
                first_days = company.caw_installment_days or 30
                period = company.caw_installment_period or "months"
                cutoff_day = company.caw_cutoff_day or 0
            withdrawal._caw_generate_installments(
                count=count, first_days=first_days, period=period, cutoff_day=cutoff_day
            )
            withdrawal._caw_create_picking()
            withdrawal.is_confirmed = True
            withdrawal.message_post(body=_("Retiro confirmado por %s.", self.env.user.display_name))
        return True

    def _caw_check_limit(self, force=False):
        """Evalúa saldo actual + total del retiro contra el límite de la cuenta.

        Devuelve el texto de advertencia en modo 'warn' (o vacío si no se supera).
        En modo 'block' levanta UserError salvo que `force` sea True.
        """
        self.ensure_one()
        account = self.account_id.sudo()
        if account.limit_mode == "none" or not account.credit_limit:
            return ""
        projected = account.balance + self.amount_total
        if self.currency_id.compare_amounts(projected, account.credit_limit) <= 0:
            return ""
        message = _(
            "El retiro deja a %(partner)s con un saldo de %(projected)s, "
            "por encima de su límite de %(limit)s.",
            partner=self.partner_id.display_name,
            projected=projected,
            limit=account.credit_limit,
        )
        if account.limit_mode == "block" and not force:
            raise UserError(_(
                "%(message)s\n\nSolo un Manager de Cuenta Corriente puede forzar este retiro.",
                message=message,
            ))
        return message

    def _caw_check_manager(self):
        """Bloquea en Python las acciones reservadas al Manager de Cuenta Corriente.

        Complementa (no reemplaza) el `groups` de los botones en la vista: cubre
        llamadas por código (RPC, otros módulos, shell) que no pasan por el form.
        """
        if not self.env.user.has_group("checking_account_withdrawals.group_cc_manager"):
            raise AccessError(_("Solo un Manager de Cuenta Corriente puede realizar esta acción."))

    def action_cancel(self):
        """Cancela el retiro. Se bloquea si tiene pagos imputados o el albarán ya se validó."""
        self._caw_check_manager()
        for withdrawal in self:
            if withdrawal.is_cancelled:
                raise UserError(_("El retiro %s ya está cancelado.", withdrawal.name))
            allocations = withdrawal.installment_ids.mapped("allocation_ids").filtered(
                lambda a: a.payment_id.state == "posted"
            )
            if allocations:
                raise UserError(_(
                    "El retiro %(name)s tiene pagos imputados por %(amount)s. "
                    "Anulá primero esos pagos y volvé a intentar la cancelación.",
                    name=withdrawal.name,
                    amount=sum(allocations.mapped("amount")),
                ))
            if withdrawal.picking_id and withdrawal.picking_id.state == "done":
                raise UserError(_(
                    "El retiro %s tiene el albarán validado (el stock ya se entregó). "
                    "Gestioná una devolución antes de cancelarlo.",
                    withdrawal.name,
                ))
            if withdrawal.picking_id:
                withdrawal.picking_id.sudo().action_cancel()
            withdrawal.installment_ids.unlink()
            withdrawal.is_cancelled = True
            withdrawal.message_post(body=_(
                "Retiro cancelado por %s.", self.env.user.display_name
            ))
        return True

    def action_draft(self):
        """Devuelve a borrador un retiro cancelado, para corregirlo."""
        self._caw_check_manager()
        for withdrawal in self:
            if not withdrawal.is_cancelled:
                raise UserError(_("Solo se puede reabrir un retiro cancelado."))
            vals = {"is_cancelled": False, "is_confirmed": False}
            # Si el albarán quedó validado antes de cancelar (caso legado / dato migrado),
            # no se limpia: regenerarlo duplicaría el descuento de stock ya hecho. En la
            # práctica esto ya no ocurre porque action_cancel bloquea la cancelación con
            # albarán 'done', pero se mantiene el resguardo por robustez.
            if not (withdrawal.picking_id and withdrawal.picking_id.state == "done"):
                vals["picking_id"] = False
            withdrawal.write(vals)
        return True

    def action_open_confirm_wizard(self):
        """Abre el wizard de confirmación con el plan de cuotas y el chequeo de límite."""
        self.ensure_one()
        self._caw_check_confirmable()
        return {
            "type": "ir.actions.act_window",
            "name": _("Confirmar retiro %s", self.name),
            "res_model": "caw.confirm.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_withdrawal_id": self.id},
        }
