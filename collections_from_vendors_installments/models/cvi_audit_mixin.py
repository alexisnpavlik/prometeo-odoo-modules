# -*- coding: utf-8 -*-
from odoo import models


class CviAuditMixin(models.AbstractModel):
    """Mixin compartido para dejar rastro de auditoría (RN-08) en cvi.card,
    cvi.installment y cvi.payment sin duplicar lógica.
    """

    _name = "cvi.audit.mixin"
    _description = "Mixin de auditoría para cobranza a vendedores en cuotas"

    def _cvi_log(self, body):
        """Registra un mensaje de auditoría en el chatter del registro (RN-08:
        toda operación relevante queda auditada con usuario y fecha).

        Los vendedores y cobradores de esta venta domiciliaria son personal de
        calle: es muy probable que su usuario de Odoo no tenga email cargado.
        En Odoo 18, `message_post` sin fallback levanta UserError cuando el
        partner del usuario actuante no tiene email ("Unable to send message,
        please configure the sender's email address."). Para no bloquear
        operaciones de negocio por esto, si el usuario no tiene email hacemos
        el post con sudo() indicando explícitamente author_id (preserva la
        atribución real) y un email_from de respaldo (empresa, o un
        placeholder no entregable si la empresa tampoco tiene email).
        """
        self.ensure_one()
        user = self.env.user
        if user.partner_id.email:
            return self.message_post(body=body)
        company_email = self.env.company.email
        fallback_email_from = company_email or "sin-email@cvi.local"
        return self.sudo().message_post(
            body=body,
            author_id=user.partner_id.id,
            email_from=fallback_email_from,
        )
