from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInternalCompanyBadge(TransactionCase):
    """Detección de empresas internas para el banner de ventas, transferencias y facturas."""

    @classmethod
    def setUpClass(cls):
        """Crea una empresa interna con dirección hija y un cliente común."""
        super().setUpClass()
        cls.company = cls.env["res.company"].create({"name": "Sucursal Test Badge"})
        cls.company_partner = cls.company.partner_id
        cls.child_address = cls.env["res.partner"].create({
            "name": "Depósito Sucursal Badge",
            "parent_id": cls.company_partner.id,
            "type": "delivery",
        })
        cls.customer = cls.env["res.partner"].create({"name": "Cliente Común Badge", "is_company": True})

    def test_company_partner_is_internal(self):
        """El contacto de una empresa propia es interno y muestra su nombre."""
        self.assertTrue(self.company_partner.is_internal_company)
        self.assertEqual(self.company_partner.internal_company_name, "Sucursal Test Badge")

    def test_child_address_is_internal(self):
        """Una dirección hija de la empresa también cuenta como interna."""
        self.assertTrue(self.child_address.is_internal_company)
        self.assertEqual(self.child_address.internal_company_name, "Sucursal Test Badge")

    def test_regular_customer_is_not_internal(self):
        """Un cliente cualquiera no es interno."""
        self.assertFalse(self.customer.is_internal_company)
        self.assertFalse(self.customer.internal_company_name)

    def test_sale_order_flag_follows_partner(self):
        """El pedido de venta refleja la empresa interna al elegir el cliente, sin guardar."""
        form = Form(self.env["sale.order"])
        form.partner_id = self.company_partner
        self.assertTrue(form.partner_is_internal_company)
        form.partner_id = self.customer
        self.assertFalse(form.partner_is_internal_company)

    def test_picking_flag(self):
        """La transferencia refleja la empresa interna del contacto."""
        picking_type = self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        picking = self.env["stock.picking"].new({
            "picking_type_id": picking_type.id,
            "partner_id": self.child_address.id,
        })
        self.assertTrue(picking.partner_is_internal_company)
        self.assertEqual(picking.partner_internal_company_name, "Sucursal Test Badge")

    def test_invoice_flag(self):
        """La factura refleja la empresa interna del cliente."""
        move = self.env["account.move"].new({"move_type": "out_invoice", "partner_id": self.company_partner.id})
        self.assertTrue(move.partner_is_internal_company)
        move = self.env["account.move"].new({"move_type": "out_invoice", "partner_id": self.customer.id})
        self.assertFalse(move.partner_is_internal_company)
