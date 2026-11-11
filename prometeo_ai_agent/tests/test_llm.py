import json
from unittest.mock import MagicMock, patch

import requests

from odoo.tests import tagged
from odoo.tests.common import BaseCase

from odoo.addons.prometeo_ai_agent import llm

TOOL = {"name": "search_count", "description": "cuenta",
        "parameters": {"type": "object", "properties": {"model": {"type": "string"}, "domain": {"type": "string"}},
                       "required": ["model", "domain"]}}
ARGS = {"model": "res.partner", "domain": "[]"}
USER = [{"role": "user", "content": "hi"}]


def fake_response(status=200, body=None, text=None):
    """Respuesta HTTP simulada."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text if text is not None else json.dumps(body or {})
    resp.json.side_effect = (lambda: body) if body is not None else (lambda: json.loads(resp.text))
    return resp


class _AdapterMixin:
    """Tests comunes a los tres adaptadores. Cada subclase define los cuerpos nativos."""

    provider = None
    allow_inherited_tests_method = True

    def post(self, body, status=200):
        return patch("requests.post", return_value=fake_response(status, body))

    def history(self):
        """Historial user → assistant con tool_call → tool."""
        return USER + [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "search_count", "arguments": ARGS}],
             "raw": None, "raw_provider": None},
            {"role": "tool", "tool_call_id": "call_1", "name": "search_count", "content": '{"count": 7}'},
        ]

    def test_text_reply(self):
        with self.post(self.text_body()):
            r = llm.chat(self.provider, "m", "sys", USER, [], 30)
        self.assertEqual((r["text"], r["tool_calls"], r["input_tokens"], r["output_tokens"]), ("hola", [], 10, 3))
        self.assertEqual(r["raw_provider"], self.provider["type"])

    def test_tool_call_reply(self):
        with self.post(self.tool_body()):
            r = llm.chat(self.provider, "m", "sys", USER, [TOOL], 30)
        self.assertEqual(r["tool_calls"][0]["name"], "search_count")
        self.assertEqual(r["tool_calls"][0]["arguments"], ARGS)
        self.assertTrue(r["tool_calls"][0]["id"])

    def test_roundtrip_sends_tool_result(self):
        with self.post(self.text_body()) as mock:
            llm.chat(self.provider, "m", "sys", self.history(), [TOOL], 30)
        sent = mock.call_args.kwargs["json"]
        self.check_tool_result_sent(sent)

    def test_http_error_raises_without_key(self):
        with patch("requests.post", return_value=fake_response(429, text="rate limited " + self.provider["api_key"])):
            with self.assertRaises(llm.LlmError) as cm:
                llm.chat(self.provider, "m", "sys", USER, [], 30)
        self.assertEqual(cm.exception.status, 429)
        self.assertNotIn(self.provider["api_key"], str(cm.exception))

    def test_empty_response_raises(self):
        with self.post(self.empty_body()):
            with self.assertRaises(llm.LlmError):
                llm.chat(self.provider, "m", "sys", USER, [], 30)

    def test_invalid_json_raises(self):
        with patch("requests.post", return_value=fake_response(200, text="<html>")):
            with self.assertRaises(llm.LlmError):
                llm.chat(self.provider, "m", "sys", USER, [], 30)

    def test_timeout_raises(self):
        with patch("requests.post", side_effect=requests.Timeout("slow")):
            with self.assertRaises(llm.LlmError):
                llm.chat(self.provider, "m", "sys", USER, [], 30)

    def test_list_models(self):
        with patch("requests.get", return_value=fake_response(200, self.models_body())):
            models = llm.list_models(self.provider)
        self.assertIn({"name": self.expected_model, "label": self.expected_label}, models)


@tagged("post_install", "-at_install")
class TestAnthropic(_AdapterMixin, BaseCase):
    provider = {"type": "anthropic", "api_key": "sk-ant-secret", "base_url": "https://api.anthropic.com"}
    expected_model, expected_label = "claude-x", "Claude X"

    def text_body(self):
        return {"content": [{"type": "text", "text": "hola"}], "usage": {"input_tokens": 10, "output_tokens": 3}}

    def tool_body(self):
        return {"content": [{"type": "tool_use", "id": "toolu_1", "name": "search_count", "input": ARGS}],
                "usage": {"input_tokens": 10, "output_tokens": 3}}

    def empty_body(self):
        return {"content": [], "usage": {"input_tokens": 1, "output_tokens": 0}}

    def models_body(self):
        return {"data": [{"id": "claude-x", "display_name": "Claude X"}]}

    def check_tool_result_sent(self, sent):
        self.assertEqual(sent["system"], "sys")
        self.assertIn("max_tokens", sent)
        last = sent["messages"][-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(last["content"][0]["type"], "tool_result")
        self.assertEqual(last["content"][0]["tool_use_id"], "call_1")
        self.assertEqual(sent["messages"][-2]["content"][-1]["type"], "tool_use")


@tagged("post_install", "-at_install")
class TestOpenAi(_AdapterMixin, BaseCase):
    provider = {"type": "openai", "api_key": "sk-openai-secret", "base_url": "https://api.openai.com/v1"}
    expected_model, expected_label = "gpt-x", "gpt-x"

    def text_body(self):
        return {"choices": [{"message": {"role": "assistant", "content": "hola"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3}}

    def tool_body(self):
        return {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search_count", "arguments": json.dumps(ARGS)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3}}

    def empty_body(self):
        return {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 0}}

    def models_body(self):
        return {"data": [{"id": "gpt-x"}]}

    def check_tool_result_sent(self, sent):
        self.assertEqual(sent["messages"][0], {"role": "system", "content": "sys"})
        self.assertNotIn("max_tokens", sent)
        self.assertEqual(sent["messages"][-1], {"role": "tool", "tool_call_id": "call_1", "content": '{"count": 7}'})
        self.assertEqual(sent["messages"][-2]["tool_calls"][0]["function"]["name"], "search_count")


@tagged("post_install", "-at_install")
class TestGoogle(_AdapterMixin, BaseCase):
    provider = {"type": "google", "api_key": "AIza-secret", "base_url": "https://generativelanguage.googleapis.com/v1beta"}
    expected_model, expected_label = "gemini-x", "Gemini X"

    def text_body(self):
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": "hola"}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}

    def tool_body(self):
        return {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "search_count", "args": ARGS}, "thoughtSignature": "sig"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}

    def empty_body(self):
        return {"candidates": [], "usageMetadata": {"promptTokenCount": 1}}

    def models_body(self):
        return {"models": [
            {"name": "models/gemini-x", "displayName": "Gemini X", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embed-x", "displayName": "Embed X", "supportedGenerationMethods": ["embedContent"]},
        ]}

    def check_tool_result_sent(self, sent):
        self.assertEqual(sent["systemInstruction"]["parts"][0]["text"], "sys")
        last = sent["contents"][-1]
        self.assertEqual(last["role"], "user")
        self.assertEqual(last["parts"][0]["functionResponse"]["name"], "search_count")
        self.assertEqual(sent["contents"][-2]["parts"][-1]["functionCall"]["name"], "search_count")

    def test_output_tokens_include_thoughts(self):
        body = self.text_body()
        body["usageMetadata"]["thoughtsTokenCount"] = 4
        with self.post(body):
            r = llm.chat(self.provider, "m", "sys", USER, [], 30)
        self.assertEqual(r["output_tokens"], 7)

    def test_list_models_filters_non_chat(self):
        with patch("requests.get", return_value=fake_response(200, self.models_body())):
            names = [m["name"] for m in llm.list_models(self.provider)]
        self.assertEqual(names, ["gemini-x"])

    def test_raw_reused_only_for_same_provider(self):
        with self.post(self.tool_body()):
            r = llm.chat(self.provider, "m", "sys", USER, [TOOL], 30)
        assistant = {"role": "assistant", "content": "", "tool_calls": r["tool_calls"],
                     "raw": r["raw"], "raw_provider": r["raw_provider"]}
        tool = {"role": "tool", "tool_call_id": r["tool_calls"][0]["id"], "name": "search_count", "content": "{}"}
        with self.post(self.text_body()) as mock:
            llm.chat(self.provider, "m", "sys", USER + [assistant, tool], [TOOL], 30)
        self.assertEqual(mock.call_args.kwargs["json"]["contents"][1]["parts"][0].get("thoughtSignature"), "sig")
        assistant["raw_provider"] = "openai"
        with self.post(self.text_body()) as mock:
            llm.chat(self.provider, "m", "sys", USER + [assistant, tool], [TOOL], 30)
        self.assertNotIn("thoughtSignature", mock.call_args.kwargs["json"]["contents"][1]["parts"][0])

    def test_schema_types_uppercased(self):
        with self.post(self.text_body()) as mock:
            llm.chat(self.provider, "m", "sys", USER, [TOOL], 30)
        decl = mock.call_args.kwargs["json"]["tools"][0]["functionDeclarations"][0]
        self.assertEqual(decl["parameters"]["type"], "OBJECT")
        self.assertEqual(decl["parameters"]["properties"]["model"]["type"], "STRING")
