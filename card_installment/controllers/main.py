from odoo import http
from odoo.http import request


class CardInstallmentController(http.Controller):

    @http.route('/pos/installments', type='json', auth='user', cors="*", csrf=False)
    def get_installments(self, card_id, amount_total):
        # auth='user' + sin sudo: respeta los derechos de acceso y las reglas
        # multi-compañía definidas para account.card.installment.
        Installment = request.env['account.card.installment']

        installments = Installment.search([
            ('card_id', '=', card_id),
            ('active', '=', True),
        ])

        return installments.card_installment_tree(amount_total)

    @http.route('/pos/get_payment_method_card', type='json', auth='user', cors="*", csrf=False)
    def get_payment_method_card(self, payment_method_id):
        """Devuelve el card_id asociado a un pos.payment.method."""
        if not payment_method_id:
            return {'card_id': False}

        payment_method = request.env['pos.payment.method'].browse(payment_method_id)

        if payment_method.exists() and payment_method.card_id:
            return {
                'card_id': payment_method.card_id.id,
                'card_name': payment_method.card_id.name,
            }

        return {'card_id': False}
