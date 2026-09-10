# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CawWithdrawalLine(models.Model):
    _name = "caw.withdrawal.line"
    _description = "Línea de retiro de cuenta corriente"
    _order = "withdrawal_id, sequence, id"

    withdrawal_id = fields.Many2one(
        comodel_name="caw.withdrawal",
        string="Retiro",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        related="withdrawal_id.company_id",
        store=True,
        index=True,
    )
    currency_id = fields.Many2one(related="withdrawal_id.currency_id", readonly=True)
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Producto",
        required=True,
        ondelete="restrict",
    )
    name = fields.Char(string="Descripción")
    quantity = fields.Float(
        string="Cantidad",
        default=1.0,
        required=True,
        digits="Product Unit of Measure",
    )
    price_unit = fields.Float(
        string="Precio unitario",
        required=True,
        digits="Product Price",
    )
    price_subtotal = fields.Monetary(
        string="Subtotal",
        compute="_compute_price_subtotal",
        store=True,
        currency_field="currency_id",
    )
    caw_price_editable = fields.Boolean(
        string="Precio editable por el usuario actual",
        compute="_compute_caw_price_editable",
        help="Solo un Manager de Cuenta Corriente puede editar el precio unitario. "
             "Campo técnico para controlar el readonly de price_unit en la vista: no se "
             "duplica el <field> de price_unit con groups complementarios porque Odoo no "
             "resuelve bien dos nodos con el mismo nombre dentro de una misma lista "
             "editable (el campo quedaba sin trackear y disparaba un falso 'obligatorio').",
    )

    @api.depends_context("uid")
    @api.depends(
        "withdrawal_id.is_confirmed",
        "withdrawal_id.is_cancelled",
        "withdrawal_id.picking_state",
        "withdrawal_id.installment_ids.allocation_ids.payment_id.state",
    )
    def _compute_caw_price_editable(self):
        """True para un Manager, mientras el retiro admita corrección de precios."""
        is_manager = self.env.user.has_group("checking_account_withdrawals.group_cc_manager")
        for line in self:
            line.caw_price_editable = bool(
                is_manager and line.withdrawal_id._caw_price_correctable()
            )

    @api.depends("quantity", "price_unit")
    def _compute_price_subtotal(self):
        """Subtotal de la línea, sin impuestos."""
        for line in self:
            line.price_subtotal = line.quantity * line.price_unit

    @api.constrains("quantity", "price_unit")
    def _check_positive_values(self):
        """Cantidad y precio no pueden ser negativos."""
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_("La cantidad de la línea debe ser mayor a cero."))
            if line.price_unit < 0:
                raise ValidationError(_("El precio unitario no puede ser negativo."))

    def _caw_price_unit(self):
        """Precio unitario del producto según la lista de precios del retiro.

        Sin lista configurada se usa el precio base del producto (comportamiento
        previo del módulo). Con lista, se respeta lo que la lista resuelva: precio
        fijo por producto o porcentaje de descuento sobre el precio base.
        """
        self.ensure_one()
        product = self.product_id
        if not product:
            return 0.0
        pricelist = self.withdrawal_id.pricelist_id
        if not pricelist:
            return product.list_price
        kwargs = {"date": self.withdrawal_id.date or fields.Date.context_today(self)}
        if self.withdrawal_id.currency_id:
            kwargs["currency"] = self.withdrawal_id.currency_id
        return pricelist._get_product_price(product, self.quantity or 1.0, **kwargs)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Propone descripción y precio del producto según la lista del retiro."""
        for line in self:
            if line.product_id:
                line.name = line.product_id.display_name
                line.price_unit = line._caw_price_unit()

    @api.onchange("quantity")
    def _onchange_quantity(self):
        """Recalcula el precio: las reglas de la lista pueden depender de la cantidad.

        Solo actúa si hay lista: sin ella el precio base no depende de la cantidad y
        pisarlo borraría un ajuste manual del Manager sin motivo.
        """
        for line in self:
            if line.product_id and line.withdrawal_id.pricelist_id:
                line.price_unit = line._caw_price_unit()

    def _caw_check_not_locked(self):
        """Bloquea la edición/borrado directo de líneas de un retiro confirmado o cancelado.

        Mismo criterio que `caw.withdrawal.write` usa para bloquear `line_ids`: evita que
        el Operador (con CRUD completo en el ACL de esta línea) altere el total de un
        retiro ya confirmado escribiendo directamente sobre `caw.withdrawal.line`.
        También cubre el retiro entregado y sin confirmar: el stock ya salió, así que
        cambiar producto o cantidad dejaría el albarán en desacuerdo con el retiro.
        """
        if any(line.withdrawal_id.is_confirmed or line.withdrawal_id.is_cancelled for line in self):
            raise UserError(_("No se pueden modificar las líneas de un retiro confirmado o cancelado."))
        if any(
            line.withdrawal_id.picking_id and line.withdrawal_id.picking_id.state == "done"
            for line in self
        ):
            raise UserError(_("No se pueden modificar las líneas de un retiro ya entregado."))

    def write(self, vals):
        """Impide editar directamente una línea de un retiro confirmado o cancelado.

        Si `vals` reasigna `withdrawal_id`, `_caw_check_not_locked()` solo ve el retiro
        de origen (el actual, leído antes del cambio): una línea de un borrador podía
        reasignarse hacia un retiro ya confirmado sin error, alterando su `amount_total`.
        Se agrega el chequeo del retiro de destino.

        Única excepción al bloqueo: la corrección de precios de un Manager. Se valida
        acá (y no solo en el padre) porque el write llega igual por los dos caminos, y
        después se reajustan las cuotas al total corregido.
        """
        price_only = bool(vals) and not (set(vals) - {"price_unit"})
        withdrawals = self.mapped("withdrawal_id")
        if price_only:
            withdrawals._caw_check_price_correction()
        else:
            self._caw_check_not_locked()
        if "withdrawal_id" in vals:
            target = self.env["caw.withdrawal"].browse(vals["withdrawal_id"])
            if target.is_confirmed or target.is_cancelled:
                raise UserError(_("No se pueden agregar líneas a un retiro confirmado o cancelado."))
        res = super().write(vals)
        if price_only:
            withdrawals.filtered("is_confirmed")._caw_resync_installments()
        return res

    def unlink(self):
        """Impide borrar directamente una línea de un retiro confirmado o cancelado."""
        self._caw_check_not_locked()
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        """Impide crear líneas nuevas en un retiro ya confirmado o cancelado.

        El ACL le da CRUD completo al Operador sobre esta línea (necesario para armar
        el retiro en borrador), así que sin este guard podía agregar líneas después de
        confirmar y alterar el total sin pasar por ningún chequeo. No se puede usar
        `_caw_check_not_locked()` tal cual (lee `line.withdrawal_id` sobre un recordset
        ya existente): acá se resuelve `withdrawal_id` desde cada `vals` antes de crear.
        """
        withdrawal_ids = {vals.get("withdrawal_id") for vals in vals_list if vals.get("withdrawal_id")}
        withdrawals = self.env["caw.withdrawal"].browse(withdrawal_ids)
        locked = withdrawals.filtered(lambda w: w.is_confirmed or w.is_cancelled)
        if locked:
            raise UserError(_("No se pueden agregar líneas a un retiro confirmado o cancelado."))
        return super().create(vals_list)
