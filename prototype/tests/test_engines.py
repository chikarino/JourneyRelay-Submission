from __future__ import annotations

import http.client
import json
import os
import unittest
from unittest.mock import patch

from backend.analysis import AnalysisError
from backend.engines import OpenAICompatEngine, OllamaEngine, ThinkSplitter


class _StreamResponse:
    """Fake urllib response yielding the given byte lines."""
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self) -> bytes:
        return b"".join(self._lines)


def ollama_lines(content: str, thinking: str = "旅客想表達…") -> list[bytes]:
    out = [
        json.dumps({"message": {"role": "assistant", "thinking": thinking}, "done": False}).encode(),
        json.dumps({"message": {"role": "assistant", "content": content}, "done": False}).encode(),
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}).encode(),
    ]
    return [line + b"\n" for line in out]


def sse_lines(deltas: list[dict]) -> list[bytes]:
    out = [b'data: ' + json.dumps(d).encode() + b"\n" for d in deltas]
    return out + [b"data: [DONE]\n"]


class ThinkSplitterTests(unittest.TestCase):
    def test_splits_reasoning_from_answer(self) -> None:
        sp = ThinkSplitter()
        th, co = sp.feed('思考中<think>hidden reasoning')
        self.assertEqual(co, "思考中")
        th2, co2 = sp.feed(" part</think>{\"needs\":")
        self.assertEqual(th + th2, "hidden reasoning part")
        self.assertEqual(co2, '{"needs":')
        th3, co3 = sp.feed("[]}")
        th4, co4 = sp.flush()
        self.assertEqual((th3 + th4, co3 + co4), ("", "[]}"))

    def test_tags_split_across_chunks(self) -> None:
        sp = ThinkSplitter()
        self.assertEqual(sp.feed("<thi"), ("", ""))  # a partial tag is held back
        self.assertEqual(sp.feed("nk>abc</th"), ("abc", ""))
        self.assertEqual(sp.feed("ink>done"), ("", "done"))


class ConversationEngineTests(unittest.TestCase):
    def test_both_engines_send_structured_chat_without_streaming_reasoning(self):
        messages = [{"role": "system", "content": "Choose tools."}, {"role": "user", "content": "Help with queues"}]
        schema = {"type": "object", "properties": {"calls": {"type": "array"}}}
        for kind in ("local", "api"):
            with self.subTest(engine=kind), patch.dict(os.environ, {"API_LLM_API_KEY": "test-key"}):
                engine = OllamaEngine() if kind == "local" else OpenAICompatEngine()
                obj = {"message": {"content": '{"calls":[]}', "thinking": "private reasoning"}} if kind == "local" else {
                    "choices": [{"message": {"content": '{"calls":[]}', "reasoning_content": "private reasoning"}}]}
                opener = "OLLAMA_OPENER" if kind == "local" else "API_OPENER"
                with patch(f"backend.engines.{opener}.open", return_value=_StreamResponse([json.dumps(obj).encode()])) as send:
                    self.assertEqual(engine.chat_json(messages, schema), {"calls": []})
                payload = json.loads(send.call_args.args[0].data)
                self.assertFalse(payload["stream"])
                self.assertEqual(payload["messages"][-1], messages[-1])
                if kind == "local":
                    self.assertEqual(payload["format"], schema)
                    self.assertFalse(payload["think"])
                else:
                    self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_both_engines_reject_malformed_conversation_responses(self):
        with patch.dict(os.environ, {"API_LLM_API_KEY": "test-key"}):
            for engine, opener, objects in (
                (OllamaEngine(), "OLLAMA_OPENER", [{"message": "bad"}, {"message": {"content": "[]"}}]),
                (OpenAICompatEngine(), "API_OPENER", [{"choices": []}, {"choices": [{"message": {"content": "not json"}}]}]),
            ):
                for obj in objects:
                    with self.subTest(response=obj), patch(f"backend.engines.{opener}.open", return_value=_StreamResponse([json.dumps(obj).encode()])):
                        with self.assertRaises(AnalysisError):
                            engine.chat_json([], {})


    def test_a_reply_cut_off_mid_stream_is_an_engine_error(self):
        class CutOff:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self): raise http.client.IncompleteRead(b"")
        with patch.dict(os.environ, {"API_LLM_API_KEY": "test-key"}), \
                patch("backend.engines.API_OPENER.open", return_value=CutOff()):
            with self.assertRaises(AnalysisError) as caught:
                OpenAICompatEngine().chat_json([], {})
        self.assertEqual(caught.exception.code, "unreachable")


class OllamaEngineTests(unittest.TestCase):
    def test_stream_yields_thinking_then_analysis(self) -> None:
        content = json.dumps({"needs": [{"code": "GUIDE", "scope": "full"}], "situation": "需要專人引路。"})
        engine = OllamaEngine()
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434",
                                     "LOCAL_LLM_MODEL": "qwen3.5:9b"}):
            with patch("backend.engines.OLLAMA_OPENER.open",
                       return_value=_StreamResponse(ollama_lines(content))):
                events = list(engine.stream_analyse("請安排職員帶路。", None))
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "status")
        self.assertIn("thinking", kinds)
        self.assertEqual(kinds[-1], "analysis")
        final = events[-1]
        self.assertEqual({n.key for n in final["needs"]}, {"GUIDE:full"})
        self.assertEqual(final["situation"], "需要專人引路。")
        self.assertEqual(final["suggestions"], ())

    def test_suggestions_flow_through_stream_and_analyse(self) -> None:
        content = json.dumps({
            "needs": [],
            "suggested_needs": [{"code": "GUIDE", "scope": "full", "reason": "可以安排專人引路"}],
            "situation": "可以揀選下面嘅建議。",
        })
        engine = OllamaEngine()
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434"}):
            with patch("backend.engines.OLLAMA_OPENER.open",
                       return_value=_StreamResponse(ollama_lines(content))):
                events = list(engine.stream_analyse("我雙眼失明。", None))
                result = engine.analyse("我雙眼失明。", None)
        self.assertEqual(events[-1]["type"], "analysis")
        self.assertEqual(events[-1]["status"], "empty")
        self.assertEqual([(s.need.code, s.reason) for s in events[-1]["suggestions"]],
                         [("GUIDE", "可以安排專人引路")])
        self.assertEqual([(s.need.code, s.reason) for s in result.suggestions],
                         [("GUIDE", "可以安排專人引路")])
        self.assertEqual(result.status, "empty")

    def test_non_loopback_rejected_before_any_request(self) -> None:
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "https://models.example.com"}):
            with self.assertRaises(AnalysisError):
                OllamaEngine()

    def test_http_error_raises_safe_code(self) -> None:
        import urllib.error
        engine = OllamaEngine()
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434"}):
            with patch("backend.engines.OLLAMA_OPENER.open",
                       side_effect=urllib.error.HTTPError("u", 500, "boom", {}, None)):
                result = engine.analyse("hi", None)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "http_500")

    def test_analyse_surfaces_error_event_code(self) -> None:
        # Invalid model output becomes a terminal error EVENT; analyse() must
        # carry its code into AnalysisResult.error_code.
        engine = OllamaEngine()
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434"}):
            with patch("backend.engines.OLLAMA_OPENER.open",
                       return_value=_StreamResponse(ollama_lines("not json at all"))):
                result = engine.analyse("hi", None)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error_code, "invalid_json")

    def test_content_with_inline_think_tag_still_parses(self) -> None:
        content = '<think>reasoning</think>{"needs":[],"situation":null}'
        engine = OllamaEngine()
        with patch.dict(os.environ, {"LOCAL_LLM_BASE_URL": "http://127.0.0.1:11434"}):
            with patch("backend.engines.OLLAMA_OPENER.open",
                       return_value=_StreamResponse(ollama_lines(content, thinking=""))):
                events = list(engine.stream_analyse("我有自閉症。", None))
        self.assertEqual(events[-1]["type"], "analysis")
        self.assertEqual(events[-1]["needs"], ())


class OpenAICompatEngineTests(unittest.TestCase):
    ENV = {"API_LLM_BASE_URL": "https://api.example.com/v1",
           "API_LLM_API_KEY": "sk-test", "API_LLM_MODEL": "glm-4.6"}

    def test_key_is_required_and_deepseek_is_the_default(self) -> None:
        with patch.dict(os.environ, {"API_LLM_API_KEY": ""}):
            with self.assertRaises(AnalysisError):
                OpenAICompatEngine()
        with patch.dict(os.environ, {"API_LLM_API_KEY": "sk-test", "API_LLM_BASE_URL": "",
                                     "API_LLM_MODEL": ""}):
            engine = OpenAICompatEngine()
        self.assertEqual((engine.base_url, engine.model), ("https://api.deepseek.com", "deepseek-flash"))

    def test_request_meets_deepseek_json_mode(self) -> None:
        sent = []

        def capture(req, timeout):
            sent.append(req)
            return _StreamResponse(sse_lines([{"choices": [{"delta": {"content": '{"needs":[]}'}}]}]))

        with patch.dict(os.environ, {"API_LLM_API_KEY": "sk-test", "API_LLM_BASE_URL": "",
                                     "API_LLM_MODEL": ""}):
            engine = OpenAICompatEngine()
            with patch("backend.engines.API_OPENER.open", side_effect=capture):
                list(engine.stream_analyse("請安排預先登機。", None))
        req = sent[0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-test")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertTrue(body["stream"])
        # JSON Output is refused unless the prompt itself asks for "json".
        self.assertIn("json", body["messages"][0]["content"])
        self.assertIn("請安排預先登機。", body["messages"][1]["content"])

    def test_reasoning_content_stream(self) -> None:
        content = json.dumps({"needs": [{"code": "PREBOARD", "scope": "full"}], "situation": "想預先登機。"})
        deltas = [
            {"choices": [{"delta": {"reasoning_content": "想一想…"}}]},
            {"choices": [{"delta": {"content": content}}]},
        ]
        with patch.dict(os.environ, self.ENV):
            engine = OpenAICompatEngine()
            with patch("backend.engines.API_OPENER.open", return_value=_StreamResponse(sse_lines(deltas))):
                events = list(engine.stream_analyse("請安排預先登機。", None))
        self.assertEqual(events[-1]["type"], "analysis")
        self.assertEqual({n.key for n in events[-1]["needs"]}, {"PREBOARD:full"})
        self.assertEqual(events[-1]["situation"], "想預先登機。")

    def test_inline_think_tags_stream(self) -> None:
        content = "<think>deep thought</think>" + json.dumps({"needs": [], "situation": "冇特別需要。"})
        deltas = [{"choices": [{"delta": {"content": content}}]}]
        with patch.dict(os.environ, self.ENV):
            engine = OpenAICompatEngine()
            with patch("backend.engines.API_OPENER.open", return_value=_StreamResponse(sse_lines(deltas))):
                events = list(engine.stream_analyse("多謝，冇特別需要。", None))
        self.assertEqual(events[-1]["needs"], ())
        self.assertEqual(events[-1]["situation"], "冇特別需要。")

    def test_invalid_output_is_honest_error(self) -> None:
        deltas = [{"choices": [{"delta": {"content": "not json"}}]}]
        with patch.dict(os.environ, self.ENV):
            engine = OpenAICompatEngine()
            with patch("backend.engines.API_OPENER.open", return_value=_StreamResponse(sse_lines(deltas))):
                events = list(engine.stream_analyse("hi", None))
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["code"], "invalid_json")



if __name__ == "__main__":
    unittest.main()
