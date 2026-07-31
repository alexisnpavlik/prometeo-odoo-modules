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

    def setUp(self):
        super().setUp()
        self.card = self.env["cvi.card"].create({
            "partner_id": self.partner.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })

    def test_photos_are_optional(self):
        """La venta se confirma sin ninguna foto (HU-08)."""
        self.assertFalse(self.card.photo_dni)
        self.assertFalse(self.card.photo_house)
        self.card.action_confirm()
        self.assertEqual(self.card.state, "sold")

    def test_has_photos_reflects_what_was_loaded(self):
        """has_photos distingue una venta con fotos de una sin ellas."""
        self.assertFalse(self.card.has_photos)
        self.card.photo_house = _png(100, 100)
        self.assertTrue(self.card.has_photos)

    def test_big_photo_is_resized_on_save(self):
        """Una foto de celular se guarda redimensionada, no en tamaño original.

        Sin max_width/max_height cada foto entraría al filestore con varios megas: dos
        por venta, miles de ventas.
        """
        self.card.photo_dni = _png(4000, 3000)
        width, height = _size(self.card.photo_dni)
        self.assertLessEqual(width, 1600)
        self.assertLessEqual(height, 1600)

    def test_resizing_keeps_the_aspect_ratio(self):
        """El redimensionado no deforma el documento."""
        self.card.photo_dni = _png(4000, 2000)
        width, height = _size(self.card.photo_dni)
        self.assertEqual(round(width / height, 2), 2.0)

    def test_small_photo_is_left_alone(self):
        """Una imagen ya chica se guarda tal cual."""
        self.card.photo_house = _png(300, 200)
        self.assertEqual(_size(self.card.photo_house), (300, 200))

    def test_photos_can_be_loaded_after_confirming(self):
        """Las fotos no están congeladas por RN-05: se cargan o corrigen tras confirmar.

        Si photo_dni o photo_house entraran en CVI_FROZEN_FIELDS, write() las rechazaría
        y el vendedor no podría completarlas después.
        """
        self.card.action_confirm()
        self.card.photo_house = _png(100, 100)
        self.assertTrue(self.card.photo_house)

    def test_vendor_can_load_photos_of_his_own_sale(self):
        """El vendedor carga las fotos con sus propios permisos, no como administrador."""
        self.card.with_user(self.vendor_user).write({"photo_dni": _png(100, 100)})
        self.assertTrue(self.card.photo_dni)

    def test_photos_are_not_copied_to_a_duplicate(self):
        """Duplicar una venta no arrastra el documento de otro cliente."""
        self.card.photo_dni = _png(100, 100)
        copy = self.card.copy()
        self.assertFalse(copy.photo_dni)
