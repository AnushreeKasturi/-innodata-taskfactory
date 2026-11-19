"""Minimal client for any OpenAI-compatible chat-completions API (OpenAI, Gemini, OpenRouter,
LiteLLM, vLLM, Ollama, most hackathon gateways). Configured entirely from environment variables:

  TF_LLM_API_KEY        required
  TF_LLM_MODEL          required
  TF_LLM_BASE_URL       default https://api.openai.com/v1
  TF_LLM_MAX_TOKENS     default 8000
  TF_LLM_TOKENS_PARAM   default max_tokens (some newer models want max_completion_tokens)
  TF_LLM_TEMPERATURE    default 0.4; set to "" to omit (reasoning models)
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("no JSON object in model output")
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON from model: {e}") from e


@dataclass
class LLM:
    model: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 8000
    tokens_param: str = "max_tokens"
    temperature: float | None = 0.4
    log_path: Path | None = None
    usage: dict = field(default_factory=lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0})

    @classmethod
    def from_env(cls, log_path: Path | None = None) -> "LLM":
        key, model = os.environ.get("TF_LLM_API_KEY"), os.environ.get("TF_LLM_MODEL")
        if not key or not model:
            raise LLMError("set TF_LLM_API_KEY and TF_LLM_MODEL (and TF_LLM_BASE_URL for non-OpenAI endpoints); see .env.example")
        temp = os.environ.get("TF_LLM_TEMPERATURE", "0.4")
        return cls(
            model=model,
            api_key=key,
            base_url=os.environ.get("TF_LLM_BASE_URL", "https://api.openai.com/v1"),
            max_tokens=int(os.environ.get("TF_LLM_MAX_TOKENS", "8000")),
            tokens_param=os.environ.get("TF_LLM_TOKENS_PARAM", "max_tokens"),
            temperature=float(temp) if temp else None,
            log_path=log_path,
        )

    def chat(self, system: str, user: str, purpose: str = "") -> str:
        body: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            self.tokens_param: self.max_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        start = time.monotonic()
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    data = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise LLMError(f"HTTP {e.code}: {detail}") from e
            except urllib.error.URLError as e:
                if attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise LLMError(str(e)) from e
        text = data["choices"][0]["message"].get("content") or ""
        u = data.get("usage") or {}
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += u.get("completion_tokens", 0)
        self.usage["seconds"] = round(self.usage["seconds"] + time.monotonic() - start, 1)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "purpose": purpose, "model": self.model, "usage": u,
                                    "system": system, "user": user, "response": text}) + "\n")
        return text

    def chat_json(self, system: str, user: str, purpose: str = "") -> dict:
        text = self.chat(system, user, purpose)
        try:
            return extract_json(text)
        except LLMError as e:
            fix = f"{user}\n\nYour previous reply could not be parsed ({e}). Reply with ONLY the JSON object."
            return extract_json(self.chat(system, fix, purpose + ":json-retry"))
