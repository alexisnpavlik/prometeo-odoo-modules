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
