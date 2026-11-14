"""JourneyRelay — the two real AI engines.

There is no rule-engine fallback in the product. If an engine fails, callers
receive AnalysisError (or an {"type":"error"} stream event) and the UI shows an
honest error with a retry.

Both engines stream the same event sequence:
  status -> thinking* -> analysis | error

OllamaEngine talks only to a loopback host (validated before any passenger
text is sent) and never follows redirects or proxies. OpenAICompatEngine talks
to whatever OpenAI-compatible endpoint is configured via API_LLM_*; the key
never leaves the backend.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import time
import urllib.error
import urllib.request
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

from .analysis import (
    DEFAULT_API_BASE_URL, DEFAULT_API_MODEL, DEFAULT_API_TIMEOUT_SECONDS,
    DEFAULT_LOCAL_BASE_URL, DEFAULT_LOCAL_MODEL, DEFAULT_LOCAL_TIMEOUT_SECONDS,
    KEEP_ALIVE, AnalysisError, AnalysisResult, output_schema, parse_output,
    system_prompt, unwrap_final_envelope,
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _no_proxy_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler())


OLLAMA_OPENER = _no_proxy_opener()
API_OPENER = _no_proxy_opener()


def _validated_loopback_url(env_key: str, default: str) -> str:
    raw = os.getenv(env_key, default).strip() or default
    try:
        parsed = urlsplit(raw)
        parsed.port
    except ValueError as exc:
        raise AnalysisError("invalid_endpoint") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise AnalysisError("invalid_endpoint")
    host = parsed.hostname.lower()
    if host != "localhost":
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise AnalysisError("non_loopback_endpoint")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class ThinkSplitter:
    """Incrementally separate <think>…</think> reasoning from answer text."""

    def __init__(self) -> None:
        self._in_think = False
        self._tail = ""

    @staticmethod
    def _partial_suffix_len(text: str, tag: str) -> int:
        for keep in range(min(len(tag) - 1, len(text)), 0, -1):
            if text.endswith(tag[:keep]):
                return keep
        return 0

    def feed(self, chunk: str) -> tuple[str, str]:
        text = self._tail + chunk
        self._tail = ""
        thinking = answer = ""
        while text:
            if self._in_think:
                end = text.find("</think>")
                if end < 0:
                    keep = self._partial_suffix_len(text, "</think>")
                    thinking += text[: len(text) - keep]
                    self._tail = text[len(text) - keep:]
                    break
                thinking += text[:end]
                text = text[end + len("</think>"):]
                self._in_think = False
            else:
                start = text.find("<think>")
                if start < 0:
                    keep = self._partial_suffix_len(text, "<think>")
                    answer += text[: len(text) - keep]
                    self._tail = text[len(text) - keep:]
                    break
                answer += text[:start]
                text = text[start + len("<think>"):]
                self._in_think = True
        return thinking, answer

    def flush(self) -> tuple[str, str]:
        text, self._tail = self._tail, ""
        if self._in_think:
            return text, ""
        return "", text


class OllamaEngine:
    """Local Ollama on loopback: full thinking, JSON-schema constrained output."""

    name = "local"

    def __init__(self) -> None:
        self.base_url = _validated_loopback_url("LOCAL_LLM_BASE_URL", DEFAULT_LOCAL_BASE_URL)
        self.model = os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL).strip() or DEFAULT_LOCAL_MODEL
        try:
            self.timeout = max(1.0, float(os.getenv("LOCAL_LLM_TIMEOUT_SECONDS",
                                                    DEFAULT_LOCAL_TIMEOUT_SECONDS)))
        except ValueError:
            self.timeout = DEFAULT_LOCAL_TIMEOUT_SECONDS

    def model_label(self) -> str:
        return self.model

    def probe(self) -> dict:
        try:
            with OLLAMA_OPENER.open(urllib.request.Request(f"{self.base_url}/api/tags"), timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return {"reachable": False, "model": self.model, "model_installed": False}
        names = {item.get("name", "") for item in data.get("models", []) if isinstance(item, dict)}
        installed = self.model in names or f"{self.model}:latest" in names
        return {"reachable": True, "model": self.model, "model_installed": installed}

    def _payload(self, text: str, context: dict | None) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt(context)},
                {"role": "user", "content": f"<passenger_text>\n{text}\n</passenger_text>"},
            ],
            "stream": True,
            "think": True,
            "format": output_schema(),
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 4096},
        }

    def stream_analyse(self, text: str, context: dict | None) -> Iterator[dict]:
        started = time.monotonic()
        yield {"type": "status", "engine": self.name, "model": self.model}
        payload = self._payload(text, context)
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        buffer = ""
        saw_thinking_field = False
        try:
            with OLLAMA_OPENER.open(req, timeout=self.timeout) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise AnalysisError("invalid_json") from exc
                    if not isinstance(obj, dict):
                        continue
                    if obj.get("error"):
                        raise AnalysisError("model_error")
                    message = obj.get("message") or {}
                    thinking = message.get("thinking")
                    if isinstance(thinking, str) and thinking:
                        saw_thinking_field = True
                        yield {"type": "thinking", "delta": thinking}
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        buffer += content
                    if obj.get("done"):
                        break
        except urllib.error.HTTPError as exc:
            raise AnalysisError(f"http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AnalysisError("unreachable") from exc

        yield from _emit_result(buffer, self.name, self.model, started,
                                inline_think=not saw_thinking_field)

    def analyse(self, text: str, context: dict | None) -> AnalysisResult:
        return _analyse_result(self, self.stream_analyse(text, context))

    def chat_json(self, messages: list[dict], schema: dict) -> dict:
        """Structured conversation step; never expose model reasoning to passengers."""
        payload = {
            "model": self.model, "messages": messages, "stream": False,
            "think": False, "format": schema, "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 2048},
        }
        obj = _request_json(OLLAMA_OPENER, f"{self.base_url}/api/chat", payload, self.timeout)
        message = obj.get("message")
        if not isinstance(message, dict):
            raise AnalysisError("invalid_schema")
        return _chat_content(message.get("content"))


class OpenAICompatEngine:
    """DeepSeek by default; any OpenAI-compatible chat-completions endpoint via API_LLM_*."""

    name = "api"

    def __init__(self) -> None:
        self.base_url = (os.getenv("API_LLM_BASE_URL", "").strip() or DEFAULT_API_BASE_URL).rstrip("/")
        self.api_key = os.getenv("API_LLM_API_KEY", "").strip()
        self.model = os.getenv("API_LLM_MODEL", "").strip() or DEFAULT_API_MODEL
        if not self.api_key:
            raise AnalysisError("api_not_configured")
        if urlsplit(self.base_url).scheme not in {"http", "https"}:
            raise AnalysisError("invalid_endpoint")
        try:
            self.timeout = max(1.0, float(os.getenv("API_LLM_TIMEOUT_SECONDS",
                                                    DEFAULT_API_TIMEOUT_SECONDS)))
        except ValueError:
            self.timeout = DEFAULT_API_TIMEOUT_SECONDS

    def model_label(self) -> str:
        return self.model

    def probe(self) -> dict:
        configured = bool(self.base_url and self.api_key and self.model)
        if not configured:
            return {"configured": False, "reachable": False, "model": None}
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with API_OPENER.open(req, timeout=3.0) as resp:
                return {"configured": True, "reachable": resp.status == 200, "model": self.model}
        except Exception:
            return {"configured": True, "reachable": False, "model": self.model}

    def _payload(self, text: str, context: dict | None) -> dict:
        schema_text = json.dumps(output_schema(), ensure_ascii=False)
        return {
            "model": self.model,
            "messages": [
                {"role": "system",
                 # DeepSeek's JSON Output needs the word "json" in the prompt.
                 "content": system_prompt(context) + f"\nReturn only a json object matching this schema:\n{schema_text}"},
                {"role": "user", "content": f"<passenger_text>\n{text}\n</passenger_text>"},
            ],
            "stream": True,
            "stream_options": {"include_usage": False},
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }

    def stream_analyse(self, text: str, context: dict | None) -> Iterator[dict]:
        started = time.monotonic()
        yield {"type": "status", "engine": self.name, "model": self.model}
        payload = self._payload(text, context)
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        splitter = ThinkSplitter()
        buffer = ""
        try:
            with API_OPENER.open(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise AnalysisError("invalid_json") from exc
                    if not isinstance(obj, dict):
                        continue
                    choices = obj.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        yield {"type": "thinking", "delta": reasoning}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        thinking, answer = splitter.feed(content)
                        if thinking:
                            yield {"type": "thinking", "delta": thinking}
                        if answer:
                            buffer += answer
        except urllib.error.HTTPError as exc:
            raise AnalysisError(f"http_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AnalysisError("unreachable") from exc

        tail_thinking, tail_answer = splitter.flush()
        if tail_thinking:
            yield {"type": "thinking", "delta": tail_thinking}
        buffer += tail_answer
        yield from _emit_result(buffer, self.name, self.model, started, inline_think=False)

    def analyse(self, text: str, context: dict | None) -> AnalysisResult:
        return _analyse_result(self, self.stream_analyse(text, context))

    def chat_json(self, messages: list[dict], schema: dict) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content":
                          "Return only a json object matching this schema:\n" + json.dumps(schema)},
                         *messages],
            "stream": False, "response_format": {"type": "json_object"},
            "temperature": 0, "max_tokens": 2048,
        }
        obj = _request_json(API_OPENER, f"{self.base_url}/chat/completions", payload,
                            self.timeout, {"Authorization": f"Bearer {self.api_key}"})
        choices = obj.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise AnalysisError("invalid_schema")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AnalysisError("invalid_schema")
        return _chat_content(message.get("content"))


def _request_json(opener, url: str, payload: dict, timeout: float, headers=None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})}, method="POST",
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise AnalysisError(f"http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        # HTTPException covers a connection dropped mid-reply (IncompleteRead).
        raise AnalysisError("unreachable") from exc
    except (ValueError, UnicodeError) as exc:
        raise AnalysisError("invalid_json") from exc
    if not isinstance(obj, dict) or obj.get("error"):
        raise AnalysisError("invalid_schema")
    return obj


def _chat_content(content) -> dict:
    if not isinstance(content, str):
        raise AnalysisError("invalid_schema")
    # Some local models include inline thinking despite think=False.
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[1]
    try:
        obj = json.loads(content)
    except ValueError as exc:
        raise AnalysisError("invalid_json") from exc
    if not isinstance(obj, dict):
        raise AnalysisError("invalid_schema")
    return unwrap_final_envelope(obj)


def _analyse_result(engine: OllamaEngine | OpenAICompatEngine,
                    events: Iterator[dict]) -> AnalysisResult:
    """Drain a stream_analyse iterator into one AnalysisResult.

    A terminal {"type":"error"} event carries its diagnostic code into
    error_code exactly like a raised AnalysisError does.
    """
    needs = situation = None
    suggestions = ()
    referrals = ()
    status = "error"
    error_code = None
    latency = 0
    try:
        for event in events:
            if event["type"] == "analysis":
                needs, situation = event["needs"], event["situation"]
                suggestions = event.get("suggestions", ())
                referrals = event.get("referrals", ())
                status = event["status"]
                latency = event["latency_ms"]
            elif event["type"] == "error":
                error_code = event["code"]
    except AnalysisError as exc:
        error_code = exc.code
    return AnalysisResult(
        needs=needs or (), situation=situation, source=engine.name, status=status,
        latency_ms=latency, model=engine.model, error_code=error_code,
        suggestions=suggestions, referrals=referrals,
    )


def _emit_result(buffer: str, source: str, model: str, started: float, *,
                 inline_think: bool) -> Iterator[dict]:
    """Parse the buffered answer; route leftover <think> blocks; emit analysis|error."""
    latency_ms = int((time.monotonic() - started) * 1000)
    content = buffer
    if inline_think and "</think>" in content:
        content = content.rsplit("</think>", 1)[1]
    try:
        needs, situation, suggestions, referrals = parse_output(content)
    except AnalysisError as exc:
        if exc.code == "invalid_json" and inline_think:
            raise
        yield {"type": "error", "code": exc.code}
        return
    yield {
        "type": "analysis", "needs": needs, "situation": situation, "suggestions": suggestions,
        "referrals": referrals,
        "status": "ok" if needs else "empty", "latency_ms": latency_ms, "model": model,
        "source": source,
    }
