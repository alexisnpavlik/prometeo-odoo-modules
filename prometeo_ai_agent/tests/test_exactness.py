import json

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.prometeo_ai_agent.agent import loop, numbers, tools

from .common import AiAgentCase, llm_text, llm_tool
from .test_llm import USER


@tagged("post_install", "-at_install")
class TestCalculator(AiAgentCase):

    def calc(self, exprs):
        ctx = tools.new_context()
        out = json.loads(tools.execute_tool(self.env(user=self.agent_user), ctx, "calculate", {"expressions": exprs}))
        return out, ctx

    def test_exact_arithmetic_and_registered(self):
        out, ctx = self.calc(["1532.5 * 12 - 800", "(18390 / 20000) * 100"])
        self.assertEqual([r["value"] for r in out["results"]], [17590.0, 91.95])
        self.assertIn(17590.0, ctx["numbers"])

    def test_errors_are_per_expression(self):
        out, _ctx = self.calc(["1/0", "__import__('os')", "9**9**9", "round(2.345, 2)"])
        self.assertIn("error", out["results"][0])
        self.assertIn("error", out["results"][1])
        self.assertIn("error", out["results"][2])
        self.assertEqual(out["results"][3]["value"], 2.35)


@tagged("post_install", "-at_install")
class TestNumberParsing(BaseCase):

    def test_formats(self):
        self.assertEqual(numbers.numbers_in_text("Total $ 1.532,50 y 1,532.50"), [{1532.5}, {1532.5}])
        self.assertIn(1532.0, numbers.numbers_in_text("son 1.532 unidades")[0])
        self.assertIn(12.5, numbers.numbers_in_text("subió 12,5%")[0])

    def test_dates_codes_and_small_ints_ignored(self):
        text = "El 4/11/2026 a las 10:30 la orden WH/IN/00012 de 3 cajas"
        self.assertEqual(numbers.numbers_in_text(text), [])

    def test_unsupported(self):
        sources = {1532.5, 14.0, 57.14}
        self.assertEqual(numbers.unsupported("Hay 14 traslados por $ 1.532,50, el 57,1%", sources), [])
        self.assertEqual(numbers.unsupported("Hay 15 traslados", sources), ["15"])


@tagged("post_install", "-at_install")
class TestVerifierInLoop(AiAgentCase):

    def run_with(self, *responses):
        with self.fake_llm(*responses) as mock:
            r = loop.run_agent(self.env(user=self.agent_user), self.ai_model, "s", USER, tools.READ_TOOLS,
                               tools.new_context(), 5, 60)
        return r, mock

    def count_call(self):
        partners = self.env["res.partner"].with_user(self.agent_user).search_count([])
        return llm_tool("search_count", {"model": "res.partner", "domain": "[]"}), partners

    def test_correct_answer_costs_no_extra_call(self):
        call, n = self.count_call()
        r, mock = self.run_with(call, llm_text("Hay %s contactos." % n))
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(r["text"], "Hay %s contactos." % n)

    def test_invented_number_is_sent_back_once(self):
        call, n = self.count_call()
        r, mock = self.run_with(call, llm_text("Hay %s contactos." % (n + 1234)), llm_text("Hay %s contactos." % n))
        self.assertEqual(mock.call_count, 3)
        self.assertIn(str(n + 1234), mock.call_args.args[3][-1]["content"])
        self.assertEqual(r["text"], "Hay %s contactos." % n)

    def test_still_wrong_after_retry_is_flagged(self):
        call, n = self.count_call()
        r, _mock = self.run_with(call, llm_text("Hay %s contactos." % (n + 1234)), llm_text("Hay %s contactos." % (n + 999)))
        self.assertIn("no se pudieron verificar", r["text"])


@tagged("post_install", "-at_install")
class TestScopeRule(AiAgentCase):

    def test_prompt_restricts_to_business_questions(self):
        from odoo.addons.prometeo_ai_agent.agent import prompts
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertIn(prompts.OFF_TOPIC_REPLY, p)
        self.assertIn("Python", p)


@tagged("post_install", "-at_install")
class TestNoBrand(AiAgentCase):

    def test_user_facing_texts_do_not_name_odoo(self):
        import os
        from odoo.addons.prometeo_ai_agent.agent import prompts
        self.assertNotIn("Odoo", prompts.OFF_TOPIC_REPLY)
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertIn("Nunca nombres Odoo", p)
        base = os.path.dirname(os.path.dirname(__file__))
        for rel in ("static/src/xml/chat_action.xml", "views/res_config_settings_views.xml"):
            with open(os.path.join(base, rel)) as f:
                self.assertNotIn("Odoo", f.read(), rel)


@tagged("post_install", "-at_install")
class TestBusinessAdviceInScope(AiAgentCase):

    def test_prompt_allows_business_improvement_questions(self):
        from odoo.addons.prometeo_ai_agent.agent import prompts
        p = prompts.build_system_prompt(self.env(user=self.agent_user), "chat")
        self.assertIn("cómo mejorar las ventas", p)
