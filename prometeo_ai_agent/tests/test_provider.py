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
        from unittest.mock import patch
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=[]):
            settings = self.env["res.config.settings"].create({"ai_google_key": "AIza-test", "ai_anthropic_key": "sk-ant"})
            settings.execute()
        google = self.env["prometeo.ai.provider"].search([("provider_type", "=", "google")], limit=1)
        self.assertEqual(google.api_key, "AIza-test")
        # La clave no vuelve al formulario: solo su final enmascarado en el estado.
        self.assertFalse(self.env["res.config.settings"].create({}).ai_google_key)
        self.assertIn("termina en test", self.env["res.config.settings"].create({}).ai_google_status)

    def _web_open_and_save(self, changes):
        """Simula el cliente web: onchange inicial (abrir Ajustes) y guardado con todo lo recibido."""
        Settings = self.env["res.config.settings"]
        spec = {name: {} for name in Settings._fields if name.startswith("ai_")}
        values = Settings.onchange({}, [], spec)["value"]
        values = {k: (v["id"] if isinstance(v, dict) else v) for k, v in values.items()}
        values.update(changes)
        Settings.create(values).execute()
        return values

    def test_opening_and_saving_settings_keeps_keys(self):
        from unittest.mock import patch
        self.provider.with_context(skip_ai_check=True).api_key = "sk-keep"
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=[]):
            values = self._web_open_and_save({"ai_digest_hour": 9})
        self.assertFalse(values.get("ai_openai_key"), "la clave no debe viajar al navegador")
        self.assertIn("termina en keep", values["ai_openai_status"])
        self.assertEqual(values["ai_openai_base_url"], "https://api.openai.com/v1")
        self.assertEqual(self.provider.api_key, "sk-keep")
        self.assertEqual(self.provider.base_url, "https://api.openai.com/v1")

    def test_new_key_from_settings_replaces_old(self):
        from unittest.mock import patch
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=[]):
            self._web_open_and_save({"ai_openai_key": "  sk-new  "})
        self.assertEqual(self.provider.api_key, "sk-new")

    def test_clear_key_button(self):
        self.env["res.config.settings"].create({}).with_context(ai_provider_type="openai").action_ai_clear_key()
        self.assertFalse(self.provider.api_key)

    def test_fetch_models_button_from_settings(self):
        from unittest.mock import patch
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=[{"name": "gpt-z", "label": "Z"}]):
            self.env["res.config.settings"].create({}).action_ai_fetch_models_openai()
        self.assertTrue(self.env["prometeo.ai.model"].with_context(active_test=False).search_count([("name", "=", "gpt-z")]))


@tagged("post_install", "-at_install")
class TestKeyFeedback(AiAgentCase):

    def google(self):
        return self.env["prometeo.ai.provider"].search([("provider_type", "=", "google")], limit=1)

    def test_valid_key_checks_syncs_inactive_models(self):
        from unittest.mock import patch
        self.env["ir.config_parameter"].sudo().set_param("prometeo_ai_agent.default_model_id", "")
        listed = [{"name": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"}, {"name": "raro-9", "label": "Raro"}]
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=listed):
            self.google().api_key = "AIza-ok"
        g = self.google()
        self.assertEqual(g.check_state, "ok")
        self.assertIn("2 modelos", g.check_message)
        models = g.with_context(active_test=False).model_ids
        self.assertFalse(models.filtered("active"), "los modelos nuevos entran desactivados")
        self.assertFalse(self.env["prometeo.ai.model"]._get_default())
        flash = models.filtered(lambda m: m.name == "gemini-3.8-flash")
        flash.active = True
        self.assertEqual(self.env["prometeo.ai.model"]._get_default(), flash,
                         "el primer modelo activado a mano queda por defecto")

    def test_invalid_key_reports_error(self):
        from unittest.mock import patch
        from odoo.addons.prometeo_ai_agent import llm
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models",
                   side_effect=llm.LlmError("La clave de API no es válida (401). Detalle: x", status=401)):
            self.google().api_key = "malo"
        self.assertEqual(self.google().check_state, "error")
        self.assertIn("no es válida", self.google().check_message)

    def test_settings_show_status(self):
        from unittest.mock import patch
        with patch("odoo.addons.prometeo_ai_agent.llm.list_models", return_value=[{"name": "gemini-x", "label": "X"}]):
            self.google().api_key = "AIza-ok"
        self.assertIn("Clave válida", self.env["res.config.settings"].create({}).ai_google_status)

    def test_prompt_answer_style_rules(self):
        from odoo.addons.prometeo_ai_agent.agent import prompts
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertIn("fecha del último registro", p)
        self.assertIn("Saludos, agradecimientos", p)
        self.assertIn("nunca display_name", p)
