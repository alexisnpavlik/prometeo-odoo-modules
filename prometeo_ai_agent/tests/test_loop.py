from odoo.tests import tagged

from odoo.addons.prometeo_ai_agent import llm
from odoo.addons.prometeo_ai_agent.agent import loop, prompts, tools

from .common import AiAgentCase, llm_text, llm_tool

COUNT = ("search_count", {"model": "res.partner", "domain": "[]"})


@tagged("post_install", "-at_install")
class TestLoop(AiAgentCase):

    def setUp(self):
        super().setUp()
        self.uenv = self.env(user=self.agent_user)
        self.ctx = tools.new_context()

    def run_agent(self, max_tool_calls=5, max_seconds=60, extra_tools=None):
        return loop.run_agent(self.uenv, self.ai_model, "sys", [{"role": "user", "content": "hola"}],
                              tools.READ_TOOLS, self.ctx, max_tool_calls, max_seconds, extra_tools=extra_tools)

    def test_plain_answer(self):
        with self.fake_llm(llm_text("hola")):
            r = self.run_agent()
        self.assertEqual((r["status"], r["text"], r["tool_calls"]), ("done", "hola", 0))
        self.assertEqual([m["role"] for m in r["new_messages"]], ["assistant"])

    def test_tool_then_answer(self):
        with self.fake_llm(llm_tool(*COUNT, input_tokens=10, output_tokens=5), llm_text("hay N", 20, 7)) as mock:
            r = self.run_agent()
        self.assertEqual((r["status"], r["text"], r["tool_calls"]), ("done", "hay N", 1))
        self.assertEqual([m["role"] for m in r["new_messages"]], ["assistant", "tool", "assistant"])
        self.assertEqual((r["input_tokens"], r["output_tokens"]), (30, 12))
        self.assertIn('"count"', r["new_messages"][1]["content"])
        second_call_messages = mock.call_args_list[1].args[3]
        self.assertEqual(second_call_messages[-1]["role"], "tool")

    def test_tool_call_limit_marks_incomplete(self):
        with self.fake_llm(llm_tool(*COUNT), llm_text("con lo que tengo")) as mock:
            r = self.run_agent(max_tool_calls=1)
        self.assertEqual((r["status"], r["text"], r["tool_calls"]), ("incomplete", "con lo que tengo", 1))
        last_messages = mock.call_args_list[-1].args[3]
        self.assertEqual(last_messages[-1], {"role": "user", "content": loop.LIMIT_NOTICE})

    def test_final_call_ignores_new_tool_requests(self):
        with self.fake_llm(llm_tool(*COUNT), llm_tool(*COUNT)):
            r = self.run_agent(max_tool_calls=1)
        self.assertEqual((r["status"], r["tool_calls"]), ("incomplete", 1))
        self.assertEqual(r["text"], loop.INCOMPLETE_TEXT)

    def test_calls_over_limit_in_same_batch_get_error(self):
        two = llm_tool(*COUNT)
        two["tool_calls"].append({"id": "call_2", "name": COUNT[0], "arguments": COUNT[1]})
        with self.fake_llm(two, llm_text("ok")):
            r = self.run_agent(max_tool_calls=1)
        tool_msgs = [m for m in r["new_messages"] if m["role"] == "tool"]
        self.assertIn('"count"', tool_msgs[0]["content"])
        self.assertIn("límite", tool_msgs[1]["content"])

    def test_time_limit_marks_incomplete(self):
        with self.fake_llm() as mock:
            r = self.run_agent(max_seconds=0)
        self.assertEqual(r["status"], "incomplete")
        self.assertEqual(r["text"], "No llegué a terminar el análisis dentro del límite configurado.")
        mock.assert_not_called()

    def test_llm_error_propagates(self):
        with self.fake_llm(llm.LlmError("caído", status=500)):
            with self.assertRaises(llm.LlmError):
                self.run_agent()

    def test_extra_tool_takes_precedence(self):
        calls = []

        def create_alert(env, ctx, arguments):
            calls.append(arguments)
            return '{"result": "created"}'

        with self.fake_llm(llm_tool("create_alert", {"key": "k"}), llm_text("listo")):
            r = self.run_agent(extra_tools={"create_alert": create_alert})
        self.assertEqual(calls, [{"key": "k"}])
        self.assertEqual(r["new_messages"][1]["content"], '{"result": "created"}')

    def test_system_prompt_has_user_timezone_date(self):
        self.agent_user.tz = "America/Argentina/Buenos_Aires"
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertIn("America/Argentina/Buenos_Aires", p)
        self.assertIn(self.env.company.name, p)
        self.assertNotIn("create_alert", p)
        self.assertIn("create_alert", prompts.build_system_prompt(self.env(user=self.agent_user), "routine"))
