from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProductProtectedLock(TransactionCase):
    """Bloqueo de edición sobre los productos de descuento y recargo de las cajas."""

    @classmethod
    def setUpClass(cls):
        """Asigna productos de prueba como descuento/recargo de una caja y crea usuarios."""
        super().setUpClass()
        cls.config = cls.env["pos.config"].search([], limit=1) if "pos.config" in cls.env else None
        cls.fields_present = [
            f for f in ("discount_product_id", "surcharge_product_id")
            if cls.config is not None and f in cls.env["pos.config"]._fields
        ]
        Product = cls.env["product.product"]
        cls.discount = Product.create({"name": "Descuento Test Lock", "type": "consu"})
        cls.surcharge = Product.create({"name": "Recargo Test Lock", "type": "consu"})
        cls.normal = Product.create({"name": "Producto Común Test Lock", "type": "consu"})
        vals = {f: (cls.discount if f == "discount_product_id" else cls.surcharge).id for f in cls.fields_present}
        if cls.config and vals:
            cls.config.sudo().write(vals)
        cls.company = cls.env["res.company"].create({"name": "Sucursal Test Product Lock"})
        base_groups = [cls.env.ref("base.group_user").id, cls.env.ref("product.group_product_manager").id]
        cls.user = cls.env["res.users"].create({
            "name": "Stock Test Product Lock",
            "login": "stock_test_product_lock",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, base_groups)],
        })
        cls.admin = cls.env["res.users"].create({
            "name": "Admin Test Product Lock",
            "login": "admin_test_product_lock",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
            "groups_id": [(6, 0, base_groups + [cls.env.ref("base.group_system").id])],
        })

    def setUp(self):
        """Sin caja o sin ningún campo de producto de sistema no hay nada que probar."""
        super().setUp()
        if not self.config or not self.fields_present:
            self.skipTest("No hay pos.config o no están instalados pos_discount / pos_global_surcharge_button")

    def _protected(self):
        """Productos que deberían quedar bloqueados según los campos instalados."""
        products = self.env["product.product"]
        if "discount_product_id" in self.fields_present:
            products |= self.discount
        if "surcharge_product_id" in self.fields_present:
            products |= self.surcharge
        return products

    def test_user_cannot_edit_variant_or_template(self):
        """Un usuario común no puede editar ni la variante ni la plantilla."""
        for product in self._protected():
            with self.assertRaisesRegex(UserError, "protegido"):
                product.with_user(self.user).write({"default_code": "X"})
            with self.assertRaisesRegex(UserError, "protegido"):
                product.product_tmpl_id.with_user(self.user).write({"name": "Otro nombre"})

    def test_user_cannot_archive_or_unlink(self):
        """Archivar y borrar también quedan bloqueados."""
        for product in self._protected():
            with self.assertRaisesRegex(UserError, "protegido"):
                product.product_tmpl_id.with_user(self.user).action_archive()
            with self.assertRaisesRegex(UserError, "protegido"):
                product.with_user(self.user).unlink()

    def test_admin_and_sudo_can_edit(self):
        """Administradores y procesos con sudo no se ven afectados."""
        for product in self._protected():
            product.product_tmpl_id.with_user(self.admin).write({"name": f"{product.name} admin"})
            product.with_user(self.user).sudo().write({"default_code": "SUDO"})

    def test_normal_product_not_blocked(self):
        """Un producto común se edita normalmente."""
        self.normal.with_user(self.user).write({"default_code": "OK"})
        self.normal.product_tmpl_id.with_user(self.user).write({"name": "Producto editado"})
        self.assertEqual(self.normal.default_code, "OK")

    def test_fallback_without_surcharge_field(self):
        """Sin el campo de recargo (módulo no instalado) protege sólo el descuento y no falla."""
        model_cls = type(self.env["pos.config"])
        fields_without_surcharge = {k: v for k, v in model_cls._fields.items() if k != "surcharge_product_id"}
        self.patch(model_cls, "_fields", fields_without_surcharge)
        protected = self.env["product.product"]._get_protected_product_ids()
        self.assertNotIn(self.surcharge.id, protected)
        if "discount_product_id" in self.fields_present:
            self.assertIn(self.discount.id, protected)
