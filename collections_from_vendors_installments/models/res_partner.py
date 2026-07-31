# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    # El DNI es la clave para reconocer a un cliente aunque el nombre esté escrito
    # distinto, que es lo que pide HU-28. Va indexado porque cada venta lo consulta.
    cvi_dni = fields.Char(
        string="DNI",
        index=True,
        help="Documento del cliente. Sirve para detectar antecedentes aunque el "
             "nombre esté cargado de otra forma.",
    )
    cvi_problematic = fields.Boolean(
        string="Cliente problemático", default=False, tracking=True, copy=False,
    )
    cvi_problematic_reason = fields.Char(string="Motivo", copy=False)
    cvi_problematic_date = fields.Date(
        string="Marcado el", readonly=True, copy=False,
    )
    cvi_problematic_user_id = fields.Many2one(
        "res.users", string="Marcado por", readonly=True, copy=False,
    )
    cvi_card_ids = fields.One2many(
        "cvi.card", "partner_id", string="Tarjetas", readonly=True,
    )
    cvi_card_count = fields.Integer(
        string="Compras", compute="_compute_cvi_history",
    )
    cvi_recovered_count = fields.Integer(
        string="Muebles retirados", compute="_compute_cvi_history",
    )
    cvi_overdue_card_count = fields.Integer(
        string="Tarjetas en mora", compute="_compute_cvi_history",
    )
    cvi_suggest_problematic = fields.Boolean(
        string="Sugerido como problemático", compute="_compute_cvi_history",
        help="Se sugiere solo cuando el cliente tuvo un mueble retirado o tiene "
             "tarjetas en mora. No marca nada: la decisión es del administrador "
             "(HU-27).",
    )

    @api.depends(
        "cvi_card_ids.state",
        "cvi_card_ids.overdue_installment_count",
    )
    def _compute_cvi_history(self):
        """Antecedentes del cliente, para HU-27 y HU-29."""
        for partner in self:
            cards = partner.cvi_card_ids
            partner.cvi_card_count = len(cards)
            partner.cvi_recovered_count = len(
                cards.filtered(lambda c: c.state == "recovered")
            )
            partner.cvi_overdue_card_count = len(
                cards.filtered(lambda c: c.overdue_installment_count > 0)
            )
            partner.cvi_suggest_problematic = bool(
                partner.cvi_recovered_count or partner.cvi_overdue_card_count
            )

    def _cvi_same_person(self):
        """El propio contacto más los que comparten DNI (HU-28).

        Sin esto, cargar al mismo cliente dos veces con el nombre escrito distinto
        alcanzaría para que sus antecedentes no aparezcan.
        """
        self.ensure_one()
        if not self.cvi_dni:
            return self
        return self | self.sudo().search([
            ("cvi_dni", "=", self.cvi_dni),
            ("id", "!=", self.id),
        ])

    def action_mark_problematic(self):
        """Marca al cliente como mala paga, con motivo (HU-27)."""
        self.ensure_one()
        if not self.cvi_problematic_reason:
            raise UserError(_(
                "Cargá el motivo antes de marcar a %s como problemático.",
                self.display_name,
            ))
        self.write({
            "cvi_problematic": True,
            "cvi_problematic_date": fields.Date.context_today(self),
            "cvi_problematic_user_id": self.env.user.id,
        })
        return True

    def action_unmark_problematic(self):
        """Levanta la marca, por ejemplo si el cliente regularizó."""
        self.ensure_one()
        self.write({
            "cvi_problematic": False,
            "cvi_problematic_date": False,
            "cvi_problematic_user_id": False,
        })
        return True
