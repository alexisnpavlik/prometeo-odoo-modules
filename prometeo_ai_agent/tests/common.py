from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests.common import TransactionCase, new_test_user


def llm_text(text, input_tokens=10, output_tokens=5):
    """Respuesta normalizada de texto, como la devuelve llm.chat()."""
    return {"text": text, "tool_calls": [], "input_tokens": input_tokens,
            "output_tokens": output_tokens, "raw": None, "raw_provider": "openai"}


def llm_tool(name, arguments, call_id="call_1", input_tokens=10, output_tokens=5):
    """Respuesta normalizada que pide una herramienta."""
    return {"text": "", "tool_calls": [{"id": call_id, "name": name, "arguments": arguments}],
            "input_tokens": input_tokens, "output_tokens": output_tokens, "raw": None,
            "raw_provider": "openai"}


class AiAgentCase(TransactionCase):
    """Base de los tests: usuarios, proveedor y modelo por defecto."""

    @classmethod
    def setUpClass(cls):
        """Crea usuario admin del agente, usuario común, proveedor y modelo."""
        super().setUpClass()
        cls.admin_user = new_test_user(
            cls.env, login="ai_admin_test", groups="base.group_user,prometeo_ai_agent.group_admin")
        cls.agent_user = new_test_user(
            cls.env, login="ai_user_test", groups="base.group_user,prometeo_ai_agent.group_user")
        cls.provider = cls.env["prometeo.ai.provider"].create({
            "name": "OpenAI test", "provider_type": "openai", "api_key": "sk-test",
            "base_url": "https://api.openai.com/v1"})
        cls.ai_model = cls.env["prometeo.ai.model"].create({
            "provider_id": cls.provider.id, "name": "gpt-test", "label": "GPT Test",
            "active": True, "price_input": 1.0, "price_output": 2.0, "price_known": True})
        cls.env["ir.config_parameter"].sudo().set_param(
            "prometeo_ai_agent.default_model_id", cls.ai_model.id)

    @contextmanager
    def fake_llm(self, *responses):
        """Parchea llm.chat para devolver las respuestas en orden. Expone el mock."""
        with patch("odoo.addons.prometeo_ai_agent.llm.chat", side_effect=list(responses)) as mock:
            yield mock
