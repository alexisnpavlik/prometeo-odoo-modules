from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPartnerProtectedLock(TransactionCase):
    """Bloqueo de edición sobre Consumidor Final Anónimo y contactos de empresas internas."""

    @classmethod
    def setUpClass(cls):
        """Crea una empresa interna, un cliente común y un usuario sin Ajustes."""
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Sucursal Test Lock"})
        cls.company_partner = cls.company.partner_id
        cls.child_address = cls.env["res.partner"].create({
            "name": "Depósito Sucursal Test",
            "parent_id": cls.company_partner.id,
            "type": "delivery",
        })
        cls.customer = cls.env["res.partner"].create({"name": "Cliente Común Test", "is_company": True})
        cls.cfa = cls.env.ref("l10n_ar.par_cfa")
        cls.user = cls.env["res.users"].create({
            "name": "Vendedor Test Lock",
            "login": "vendedor_test_lock",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id, cls.env.ref("base.group_partner_manager").id])],
        })
        cls.admin = cls.env["res.users"].create({
            "name": "Admin Test Lock",
            "login": "admin_test_lock",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("base.group_partner_manager").id,
                cls.env.ref("base.group_system").id,
            ])],
        })

    def test_user_cannot_write_company_partner(self):
        """Un usuario común no puede editar el contacto de una empresa interna."""
        with self.assertRaisesRegex(UserError, "protegido"):
            self.company_partner.with_user(self.user).write({"phone": "123"})

    def test_user_cannot_write_cfa(self):
        """Un usuario común no puede editar Consumidor Final Anónimo."""
        with self.assertRaisesRegex(UserError, "protegido"):
            self.cfa.with_user(self.user).write({"street": "Calle falsa 123"})

    def test_user_cannot_archive_protected(self):
        """Archivar también queda bloqueado."""
        with self.assertRaisesRegex(UserError, "protegido"):
            self.company_partner.with_user(self.user).action_archive()
        with self.assertRaisesRegex(UserError, "protegido"):
            self.cfa.with_user(self.user).action_archive()

    def test_user_cannot_unlink_protected(self):
        """Borrar queda bloqueado."""
        with self.assertRaisesRegex(UserError, "protegido"):
            self.cfa.with_user(self.user).unlink()

    def test_batch_write_with_protected_is_blocked(self):
        """Un write en lote que incluye un protegido se bloquea entero."""
        batch = (self.customer | self.cfa).with_user(self.user)
        with self.assertRaisesRegex(UserError, "protegido"):
            batch.write({"phone": "lote"})

    def test_user_can_write_regular_partner(self):
        """Un cliente común (aunque sea empresa) se edita normalmente."""
        self.customer.with_user(self.user).write({"phone": "999"})
        self.assertEqual(self.customer.phone, "999")

    def test_user_can_write_child_address(self):
        """Las direcciones hijas de una empresa interna no se protegen."""
        self.child_address.with_user(self.user).write({"street": "Ruta 11 km 1000"})
        self.assertEqual(self.child_address.street, "Ruta 11 km 1000")

    def test_admin_can_write_protected(self):
        """Un administrador (Ajustes) edita todo."""
        self.company_partner.with_user(self.admin).write({"phone": "456"})
        self.cfa.with_user(self.admin).write({"phone": "ok admin"})
        self.assertEqual(self.company_partner.phone, "456")

    def test_sudo_write_passes(self):
        """Los procesos internos con sudo no se bloquean."""
        self.cfa.with_user(self.user).sudo().write({"phone": "proceso interno"})
        self.assertEqual(self.cfa.phone, "proceso interno")
