from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.prometeo_ai_agent import llm
from odoo.addons.prometeo_ai_agent.agent import loop, tools

from .common import AiAgentCase, llm_text, llm_tool
from .test_llm import USER, fake_response


@tagged("post_install", "-at_install")
class TestLiveSteps(AiAgentCase):

    def test_loop_reports_each_tool_step(self):
        steps = []
        with self.fake_llm(llm_tool("search_count", {"model": "res.partner", "domain": "[]"}), llm_text("ok")):
            loop.run_agent(self.env(user=self.agent_user), self.ai_model, "s", USER, tools.READ_TOOLS,
                           tools.new_context(), 5, 60, on_step=steps.append)
        self.assertEqual(len(steps), 1)
        self.assertIn("registros", steps[0])
        self.assertIn("res.partner", steps[0])

    def test_chat_publishes_steps_to_user(self):
        conv = self.env["prometeo.ai.conversation"].with_user(self.agent_user).create({})
        Conv = type(self.env["prometeo.ai.conversation"])
        with patch.object(Conv, "_publish_step") as publish, \
                self.fake_llm(llm_tool("search_count", {"model": "res.partner", "domain": "[]"}), llm_text("ok")):
            conv.send_message("hola")
        self.assertEqual(publish.call_count, 1)

    def test_friendly_provider_errors(self):
        prov = {"type": "google", "api_key": "k", "base_url": "https://x"}
        for status, text in ((402, "crédito"), (401, "clave"), (429, "límite")):
            with patch("requests.post", return_value=fake_response(status, text="{}")):
                with self.assertRaises(llm.LlmError) as cm:
                    llm.chat(prov, "m", "s", USER, [], 10)
            self.assertIn(text, str(cm.exception))
