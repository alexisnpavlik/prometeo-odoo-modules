# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCustomerNotes(CviCommon):
    """Las notas del cliente van al historial, no a un campo libre."""

    def test_there_is_no_free_text_note_field(self):
        """Observaciones se fue: un texto que se pisa no deja rastro de quién ni cuándo."""
        self.assertNotIn("note", self.env["cvi.customer"]._fields)

    def test_vendor_can_log_a_note_in_the_history(self):
        """El vendedor registra la nota con sus propios permisos y queda fechada.

        Registrar una nota exige escritura sobre el cliente: si el módulo dejara al
        vendedor en solo lectura, no podría anotar nada en el domicilio.
        """
        message = self.customer.with_user(self.vendor_user).message_post(
            body="Se mudó a la vuelta, atiende la hija.",
            subtype_xmlid="mail.mt_note",
        )
        self.assertEqual(message.subtype_id, self.env.ref("mail.mt_note"))
        self.assertEqual(message.author_id, self.vendor_user.partner_id)
        self.assertIn("Se mudó a la vuelta", message.body)
        self.assertIn(message, self.customer.message_ids)
