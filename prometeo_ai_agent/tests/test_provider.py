from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import AiAgentCase


@tagged("post_install", "-at_install")
class TestProvider(AiAgentCase):

    def test_default_base_url_per_type(self):
        p = self.env["prometeo.ai.provider"].new({"provider_type": "google"})
        p._onchange_provider_type()
        self.assertEqual(p.base_url, "https://generativelanguage.googleapis.com/v1beta")

    def test_credentials_without_key_raises(self):
        self.provider.api_key = False
        with self.assertRaises(UserError):
            self.provider._get_credentials()

    def test_credentials_shape(self):
        self.assertEqual(self.provider._get_credentials(), {
            "type": "openai", "api_key": "sk-test", "base_url": "https://api.openai.com/v1"})

    def test_agent_user_cannot_read_provider(self):
        with self.assertRaises(AccessError):
            self.provider.with_user(self.agent_user).read(["name"])

    def test_default_model_roundtrip(self):
        self.assertEqual(self.env["prometeo.ai.model"]._get_default(), self.ai_model)


@tagged("post_install", "-at_install")
class TestFetchModels(AiAgentCase):

    def _fetch(self, listed, prices=None):
        from unittest.mock import patch
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=listed), \
                patch.dict("odoo.addons.prometeo_ai_agent.llm.prices.KNOWN_PRICES", prices or {}, clear=True):
            return self.provider.action_fetch_models()

    def _model(self, name):
        return self.provider.with_context(active_test=False).model_ids.filtered(lambda r: r.name == name)

    def test_fetch_creates_inactive_models_with_known_price(self):
        self._fetch([{"name": "gpt-x-2026", "label": "GPT X"}], {("openai", "gpt-x"): (3.0, 9.0)})
        m = self._model("gpt-x-2026")
        self.assertEqual((m.active, m.price_input, m.price_output, m.price_known), (False, 3.0, 9.0, True))
        self.assertEqual(m.label, "GPT X")

    def test_fetch_unknown_model_has_no_price(self):
        self._fetch([{"name": "raro-1", "label": "raro-1"}])
        self.assertFalse(self._model("raro-1").price_known)

    def test_fetch_twice_keeps_edited_price_and_does_not_duplicate(self):
        self._fetch([{"name": "gpt-x-2026", "label": "GPT X"}], {("openai", "gpt-x"): (3.0, 9.0)})
        self._model("gpt-x-2026").price_input = 4.0
        self._fetch([{"name": "gpt-x-2026", "label": "GPT X"}], {("openai", "gpt-x"): (3.0, 9.0)})
        self.assertEqual(len(self._model("gpt-x-2026")), 1)
        self.assertEqual(self._model("gpt-x-2026").price_input, 4.0)

    def test_longest_prefix_wins(self):
        from odoo.addons.prometeo_ai_agent.llm import prices
        table = {("anthropic", "claude-opus-5"): (5.0, 25.0), ("anthropic", "claude-opus-5-5"): (4.0, 20.0)}
        from unittest.mock import patch
        with patch.dict(prices.KNOWN_PRICES, table, clear=True):
            self.assertEqual(prices.lookup_price("anthropic", "claude-opus-5-5-20261001"), (4.0, 20.0))
            self.assertEqual(prices.lookup_price("anthropic", "claude-opus-5-20260101"), (5.0, 25.0))
            self.assertIsNone(prices.lookup_price("openai", "claude-opus-5"))


@tagged("post_install", "-at_install")
class TestSettingsProviders(AiAgentCase):

    def test_keys_are_set_from_settings(self):
        settings = self.env["res.config.settings"].create({"ai_google_key": "AIza-test", "ai_anthropic_key": "sk-ant"})
        settings.execute()
        google = self.env["prometeo.ai.provider"].search([("provider_type", "=", "google")], limit=1)
        self.assertEqual(google.api_key, "AIza-test")
        self.assertEqual(self.env["res.config.settings"].create({}).ai_google_key, "AIza-test")

    def test_fetch_models_button_from_settings(self):
        from unittest.mock import patch
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=[{"name": "gpt-z", "label": "Z"}]):
            self.env["res.config.settings"].create({}).action_ai_fetch_models_openai()
        self.assertTrue(self.env["prometeo.ai.model"].with_context(active_test=False).search_count([("name", "=", "gpt-z")]))
