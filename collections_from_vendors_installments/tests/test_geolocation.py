# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CviCommon

# Plaza 25 de Mayo, Resistencia (Chaco).
LAT = -27.4512340
LON = -58.9866780


@tagged("post_install", "-at_install")
class TestCviGeolocation(CviCommon):

    def setUp(self):
        super().setUp()
        self.customer.write({"street": "Av. Siempreviva 742", "city": "Resistencia"})
        self.card = self.env["cvi.card"].create({
            "customer_id": self.customer.id,
            "vendor_id": self.vendor_user.id,
            "product_id": self.product.id,
            "date_sale": "2026-01-15",
            "plan_id": self.plan_3.id,
            "charge_day_month": 10,
        })
        self.card._cvi_generate_installments()

    def _installment(self):
        return self.card.installment_ids.filtered(lambda i: not i.is_commission)[0]

    def test_card_without_coordinates_has_no_geolocation(self):
        """Una venta recién cargada no tiene ubicación."""
        self.assertFalse(self.card.has_geolocation)
        self.assertFalse(self.card.map_url)

    def test_capturing_coordinates_stamps_the_date(self):
        """Grabar coordenadas sella cvi_geo_date sin que el cliente lo mande."""
        self.assertFalse(self.card.cvi_geo_date)
        self.card.write({"cvi_latitude": LAT, "cvi_longitude": LON})
        self.assertTrue(self.card.has_geolocation)
        self.assertTrue(self.card.cvi_geo_date)

    def test_map_url_uses_the_coordinates(self):
        """El mapa de la venta apunta a las coordenadas, no a la dirección."""
        self.card.write({"cvi_latitude": LAT, "cvi_longitude": LON})
        self.assertIn("27.451234", self.card.map_url)
        self.assertIn("58.986678", self.card.map_url)
        self.assertNotIn("Siempreviva", self.card.map_url)

    def test_installment_map_prefers_gps_over_the_contact_address(self):
        """La cuota lleva al punto GPS de la venta, no a la dirección del contacto (A3)."""
        self.card.write({"cvi_latitude": LAT, "cvi_longitude": LON})
        installment = self._installment()
        self.assertTrue(installment.map_is_gps)
        self.assertEqual(installment.map_url, self.card.map_url)
        self.assertNotIn("Siempreviva", installment.map_url)

    def test_installment_falls_back_to_address_and_says_so(self):
        """Sin GPS se usa la dirección, pero map_is_gps avisa que es un respaldo.

        Las ventas cargadas antes de que existiera la captura GPS no tienen
        coordenadas: sin respaldo el cobrador se quedaría sin ninguna referencia.
        """
        installment = self._installment()
        self.assertFalse(installment.map_is_gps)
        self.assertIn("Siempreviva", installment.map_url)

    def test_zero_coordinates_do_not_count_as_a_location(self):
        """(0, 0) es el punto nulo del Atlántico: significa vacío, no una venta ahí."""
        self.card.write({"cvi_latitude": 0.0, "cvi_longitude": 0.0})
        self.assertFalse(self.card.has_geolocation)
        self.assertFalse(self.card.cvi_geo_date)

    def test_clearing_the_location_wipes_the_stamp(self):
        """Borrar la ubicación deja la tarjeta como si nunca se hubiera tomado."""
        self.card.write({"cvi_latitude": LAT, "cvi_longitude": LON})
        self.card.action_clear_geolocation()
        self.assertFalse(self.card.has_geolocation)
        self.assertFalse(self.card.cvi_geo_date)
        self.assertFalse(self.card.map_url)

    def test_retaking_the_location_updates_the_stamp(self):
        """Volver a tomar la ubicación sella una fecha nueva."""
        self.card.write({"cvi_latitude": LAT, "cvi_longitude": LON})
        first_stamp = self.card.cvi_geo_date
        self.card.write({"cvi_latitude": LAT + 0.001, "cvi_longitude": LON})
        self.assertGreaterEqual(self.card.cvi_geo_date, first_stamp)

    def test_open_map_without_location_is_rejected(self):
        """Sin ubicación no hay mapa que abrir."""
        with self.assertRaises(UserError):
            self.card.action_open_map()

    def test_location_is_editable_after_confirming(self):
        """La ubicación no está congelada por RN-05: se puede corregir tras confirmar."""
        self.card.action_confirm()
        self.card.write({"cvi_latitude": LAT, "cvi_longitude": LON})
        self.assertTrue(self.card.has_geolocation)

    def test_vendor_can_record_his_own_sale_location(self):
        """El vendedor graba la ubicación con sus propios permisos, no como administrador."""
        self.card.with_user(self.vendor_user).write({
            "cvi_latitude": LAT,
            "cvi_longitude": LON,
        })
        self.assertTrue(self.card.has_geolocation)
