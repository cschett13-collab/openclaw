"""Tiny client for a local Ollama instance (the RTX 5090 compute layer).

Talks to the native Ollama HTTP API
(https://github.com/ollama/ollama/blob/main/docs/api.md). Defaults match the
stack in ../../README.md: http://127.0.0.1:11434.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1:8b"


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns an error."""


@dataclass
class OllamaClient:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: int = 180

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        """Single-shot completion. Returns the model's text response."""
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system

        url = f"{self.base_url.rstrip('/')}/api/generate"
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise OllamaError(
                f"Could not reach Ollama at {self.base_url}. Is it running "
                f"('systemctl status ollama') and is '{self.model}' pulled "
                f"('ollama pull {self.model}')?"
            ) from exc
        except requests.exceptions.HTTPError as exc:
            raise OllamaError(f"Ollama returned {resp.status_code}: {resp.text}") from exc
        return resp.json().get("response", "").strip()

    def is_up(self) -> bool:
        try:
            requests.get(f"{self.base_url.rstrip('/')}/api/tags", timeout=5).raise_for_status()
            return True
        except requests.exceptions.RequestException:
            return False
