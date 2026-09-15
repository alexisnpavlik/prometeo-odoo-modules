# -*- coding: utf-8 -*-
import base64
import io

from odoo.tests import tagged

from .common import CviCommon


def _png(width, height):
    """PNG real de las dimensiones pedidas, para ejercitar el redimensionado."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(120, 75, 103)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue())


def _size(data):
    """Alto y ancho de una imagen guardada en el campo."""
    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(data))).size


@tagged("post_install", "-at_install")
class TestCviPhotos(CviCommon):
    """Foto de la vivienda: es de la venta, porque se saca en ese domicilio."""

    def setUp(self):
        super().setUp()
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })

    def test_photos_are_optional(self):
        """La venta se confirma sin ninguna foto (HU-08)."""
        self.assertFalse(self.card.photo_house)
        self.card.action_confirm()
        self.assertEqual(self.card.state, "sold")

    def test_the_dni_photo_is_not_a_field_of_the_sale(self):
        """El documento es del cliente, no de cada compra.

        Vive en la ficha de cvi.customer: el mismo DNI no se vuelve a fotografiar
        en la segunda venta, y frente y dorso se cargan una sola vez.
        """
        self.assertNotIn("photo_dni", self.env["cvi.card"]._fields)

    def test_has_photos_reflects_what_was_loaded(self):
        """has_photos distingue una venta con foto de la vivienda de una sin ella."""
        self.assertFalse(self.card.has_photos)
        self.card.photo_house = _png(100, 100)
        self.assertTrue(self.card.has_photos)

    def test_big_photo_is_resized_on_save(self):
        """Una foto de celular se guarda redimensionada, no en tamaño original.

        Sin max_width/max_height cada foto entraría al filestore con varios megas.
        """
        self.card.photo_house = _png(4000, 3000)
        width, height = _size(self.card.photo_house)
        self.assertLessEqual(width, 1600)
        self.assertLessEqual(height, 1600)

    def test_resizing_keeps_the_aspect_ratio(self):
        """El redimensionado no deforma la fachada."""
        self.card.photo_house = _png(4000, 2000)
        width, height = _size(self.card.photo_house)
        self.assertEqual(round(width / height, 2), 2.0)

    def test_small_photo_is_left_alone(self):
        """Una imagen ya chica se guarda tal cual."""
        self.card.photo_house = _png(300, 200)
        self.assertEqual(_size(self.card.photo_house), (300, 200))

    def test_photos_can_be_loaded_after_confirming(self):
        """Las fotos no están congeladas por RN-05: se cargan o corrigen tras confirmar.

        Si photo_house entrara en CVI_FROZEN_FIELDS, write() la rechazaría y el
        vendedor no podría completarla después.
        """
        self.card.action_confirm()
        self.card.photo_house = _png(100, 100)
        self.assertTrue(self.card.photo_house)

    def test_vendor_can_load_photos_of_his_own_sale(self):
        """El vendedor carga las fotos con sus propios permisos, no como administrador."""
        self.card.with_user(self.vendor_user).write({"photo_house": _png(100, 100)})
        self.assertTrue(self.card.photo_house)

    def test_photos_are_not_copied_to_a_duplicate(self):
        """Duplicar una venta no arrastra la foto de otro domicilio."""
        self.card.photo_house = _png(100, 100)
        copy = self.card.copy()
        self.assertFalse(copy.photo_house)


@tagged("post_install", "-at_install")
class TestCviCustomerDniPhotos(CviCommon):
    """Foto del DNI: frente y dorso, en la ficha del cliente."""

    def test_customer_stores_front_and_back(self):
        """El DNI tiene dos caras y las dos se guardan por separado."""
        self.customer.write({
            "photo_dni_front": _png(200, 120),
            "photo_dni_back": _png(200, 120),
        })
        self.assertTrue(self.customer.photo_dni_front)
        self.assertTrue(self.customer.photo_dni_back)

    def test_dni_photo_is_resized_on_save(self):
        """La foto del documento entra al filestore redimensionada."""
        self.customer.photo_dni_front = _png(4000, 3000)
        width, height = _size(self.customer.photo_dni_front)
        self.assertLessEqual(width, 1600)
        self.assertLessEqual(height, 1600)

    def test_dni_resizing_keeps_the_aspect_ratio(self):
        """El redimensionado no deforma el documento: tiene que quedar legible."""
        self.customer.photo_dni_back = _png(4000, 2000)
        width, height = _size(self.customer.photo_dni_back)
        self.assertEqual(round(width / height, 2), 2.0)

    def test_has_dni_photos_needs_both_faces(self):
        """El indicador se enciende recién con las dos caras cargadas.

        Es lo que mira la administración para reclamar documentación: un frente
        solo no alcanza para tener el documento del cliente.
        """
        self.assertFalse(self.customer.has_dni_photos)
        self.customer.photo_dni_front = _png(100, 100)
        self.assertFalse(self.customer.has_dni_photos)
        self.customer.photo_dni_back = _png(100, 100)
        self.assertTrue(self.customer.has_dni_photos)

    def test_vendor_can_load_the_dni_of_a_customer(self):
        """El vendedor saca las fotos en el domicilio con sus propios permisos."""
        self.customer.with_user(self.vendor_user).write({
            "photo_dni_front": _png(100, 100),
            "photo_dni_back": _png(100, 100),
        })
        self.assertTrue(self.customer.photo_dni_front)
        self.assertTrue(self.customer.photo_dni_back)
