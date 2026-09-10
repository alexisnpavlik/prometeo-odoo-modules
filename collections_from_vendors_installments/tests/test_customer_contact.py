# -*- coding: utf-8 -*-
import base64
import io

from lxml import etree
from PIL import Image

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import CviCommon


@tagged("post_install", "-at_install")
class TestCviCustomerContact(CviCommon):
    """Datos de contacto del cliente: un solo número y la ciudad de una lista."""

    def setUp(self):
        super().setUp()
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
            "collector_id": self.collector_user.id,
        })
        self.card.action_confirm()

    def test_there_is_no_landline_field(self):
        """Quedó un solo número: el fijo no lo usa nadie para cobrar."""
        self.assertNotIn("phone", self.env["cvi.customer"]._fields)

    def test_the_agenda_shows_the_customer_mobile(self):
        """El cobrador ve el celular en la cuota, que es a donde llama de verdad."""
        self.customer.mobile = "3644 55-66-77"
        installment = self.card.installment_ids[0]
        self.assertEqual(installment.mobile, "3644 55-66-77")

    def test_the_city_hangs_from_a_province(self):
        """Una ciudad pertenece a una provincia: es lo que evita homónimas sueltas."""
        self.assertEqual(self.city.state_id, self.state)
        self.assertIn(self.state.name, self.city.display_name)

    def test_the_customer_picks_the_city_from_the_list(self):
        """La ciudad dejó de ser texto libre: se elige de las cargadas."""
        self.assertNotIn("city", self.env["cvi.customer"]._fields)
        self.customer.city_id = self.city
        self.assertEqual(self.customer.city_id, self.city)

    def test_the_province_comes_from_the_chosen_city(self):
        """La provincia no se carga a mano: sale de la ciudad, así no se contradicen."""
        self.customer.city_id = self.city
        self.assertEqual(self.customer.state_id, self.state)

    def test_the_agenda_address_uses_the_chosen_city(self):
        """El mapa del cobrador sigue armando la dirección, ahora con la ciudad elegida."""
        self.customer.write({"street": "Belgrano 123", "city_id": self.city.id})
        installment = self.card.installment_ids[0]
        self.assertEqual(installment.city, self.city.name)
        self.assertIn("Belgrano", installment.map_url)

    def test_the_vendor_cannot_invent_a_city(self):
        """Solo administración da de alta ciudades: si no, entra cinco veces escrita distinto."""
        with self.assertRaises(AccessError):
            self.env["cvi.city"].with_user(self.vendor_user).create({
                "name": "Machagai",
                "state_id": self.state.id,
            })

    def test_customer_form_requires_contact_data(self):
        """La ficha no deja guardar sin los datos necesarios para visitar y cobrar."""
        view = self.env.ref(
            "collections_from_vendors_installments.view_cvi_customer_form"
        )
        arch = etree.fromstring(view.arch.encode())
        required_by_field = {
            "dni": "1",
            "mobile": "cvi_customer_mobile_required",
            "street": "cvi_customer_street_required",
            "city_id": "cvi_customer_city_required",
            "zip": "cvi_customer_zip_required",
        }
        for field_name, required in required_by_field.items():
            with self.subTest(field=field_name):
                node = arch.xpath("//field[@name='%s']" % field_name)[0]
                self.assertEqual(node.get("required"), required)
        for field_name in ("photo_dni_front", "photo_dni_back"):
            with self.subTest(field=field_name):
                node = arch.xpath("//field[@name='%s']" % field_name)[0]
                self.assertEqual(
                    node.get("required"), "cvi_customer_dni_photos_required"
                )

    def test_new_sale_form_requires_contact_data_only_for_a_new_customer(self):
        """Buscar por DNI sigue libre; los datos son obligatorios al dar de alta."""
        view = self.env.ref(
            "collections_from_vendors_installments.view_cvi_sale_start_wizard_form"
        )
        arch = etree.fromstring(view.arch.encode())
        required_by_field = {
            "name": "searched and not found",
            "mobile": (
                "searched and not found and cvi_customer_mobile_required"
            ),
            "street": (
                "searched and not found and cvi_customer_street_required"
            ),
            "city_id": (
                "searched and not found and cvi_customer_city_required"
            ),
            "zip": "searched and not found and cvi_customer_zip_required",
        }
        for field_name, required in required_by_field.items():
            with self.subTest(field=field_name):
                node = arch.xpath(
                    "//group[@string='Cliente nuevo']/field[@name='%s']"
                    % field_name
                )[0]
                self.assertEqual(node.get("required"), required)
        for field_name in ("photo_dni_front", "photo_dni_back"):
            with self.subTest(field=field_name):
                node = arch.xpath("//field[@name='%s']" % field_name)[0]
                self.assertEqual(
                    node.get("required"),
                    "searched and not found and cvi_customer_dni_photos_required",
                )

    def test_new_sale_copies_contact_data_and_optional_dni_photos(self):
        """El alta rápida conserva dirección, celular y ambas caras opcionales del DNI."""
        wizard_model = self.env["cvi.sale.start.wizard"]
        for field_name in ("zip", "photo_dni_front", "photo_dni_back"):
            self.assertIn(field_name, wizard_model._fields)

        buffer = io.BytesIO()
        Image.new("RGB", (200, 120), color=(120, 75, 103)).save(
            buffer, format="PNG"
        )
        front = base64.b64encode(buffer.getvalue())
        back = front
        wizard = wizard_model.create({
            "dni": "45999888",
            "searched": True,
            "name": "Cliente nuevo",
            "mobile": "3644 123456",
            "street": "Belgrano 456",
            "city_id": self.city.id,
            "zip": "3500",
            "photo_dni_front": front,
            "photo_dni_back": back,
        })

        wizard.action_start_sale()

        customer = self.env["cvi.customer"]._cvi_find_by_dni("45999888")
        self.assertEqual(customer.mobile, "3644 123456")
        self.assertEqual(customer.street, "Belgrano 456")
        self.assertEqual(customer.city_id, self.city)
        self.assertEqual(customer.zip, "3500")
        self.assertTrue(customer.photo_dni_front)
        self.assertTrue(customer.photo_dni_back)
