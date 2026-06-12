from odoo import http
from odoo.http import request

class CardInstallmentController(http.Controller):

    @http.route('/pos/installments', type='json', auth='public', cors="*", csrf=False)
    def get_installments(self, card_id, amount_total):
        Installment = request.env['account.card.installment'].sudo()

        installments = Installment.search([('card_id', '=', card_id), ('active', '=', True)])

        # Usar la función del modelo
        return installments.card_installment_tree(amount_total)

    @http.route('/pos/installments/test', auth='public')
    def test_installments(self):
        return "OK"
    
    @http.route('/pos/get_payment_method_card', type='json', auth='public', cors="*", csrf=False)
    def get_payment_method_card(self, payment_method_id):
        """
        Busca el card_id asociado a un pos.payment.method.
        """
        if not payment_method_id:
            return {'card_id': False}

        # Asegúrate de que el usuario tenga permisos para leer este modelo
        payment_method = request.env['pos.payment.method'].sudo().browse(payment_method_id)

        # Si el registro existe y tiene un card_id asociado
        if payment_method.exists() and payment_method.card_id:
            return {
                'card_id': payment_method.card_id.id,
                'card_name': payment_method.card_id.name,
                # Puedes agregar más campos de account.card si los necesitas en el POS
            }
        
        return {'card_id': False}