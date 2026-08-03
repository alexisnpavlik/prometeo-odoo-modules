from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from ..services.mp_client import (
    MercadoPagoAuthError,
    MercadoPagoClient,
    MercadoPagoTransientError,
)


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


@tagged("post_install", "-at_install")
class TestMercadoPagoClient(TransactionCase):
    def setUp(self):
        super().setUp()
        self.client = MercadoPagoClient("APP_USR-fake")

    def test_search_builds_relative_window_query(self):
        """La búsqueda usa el rango por date_created y filtra approved."""
        captured = {}

        def fake_request(method, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            captured["headers"] = kwargs.get("headers")
            return _FakeResponse(200, {"paging": {"total": 0}, "results": []})

        with patch("requests.request", side_effect=fake_request):
            self.client.search_payments("NOW-5MINUTES", "NOW")

        self.assertIn("/v1/payments/search", captured["url"])
        self.assertEqual(captured["params"]["range"], "date_created")
        self.assertEqual(captured["params"]["begin_date"], "NOW-5MINUTES")
        self.assertEqual(captured["params"]["status"], "approved")
        self.assertEqual(
            captured["headers"]["Authorization"], "Bearer APP_USR-fake"
        )

    def test_401_raises_auth_error(self):
        """Un 401 es error de configuración, no reintentable."""
        with patch("requests.request", return_value=_FakeResponse(401, {"message": "invalid"})):
            with self.assertRaises(MercadoPagoAuthError):
                self.client.get_me()

    def test_500_raises_transient_error_after_retries(self):
        """Un 5xx se reintenta y termina en error transitorio."""
        with patch("requests.request", return_value=_FakeResponse(500, {})) as mocked:
            with self.assertRaises(MercadoPagoTransientError):
                self.client.get_me()
        self.assertEqual(mocked.call_count, 3)
