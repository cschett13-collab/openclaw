"""Shared infrastructure for the creative engine.

Production concerns live here so the three pipeline scripts stay readable:
  * resilient HTTP sessions (retry + backoff for connection dropouts)
  * disk-space guards (don't start a render that can't be written)
  * consistent logging
  * env-driven config (no secrets in source)
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format=LOG_FORMAT)
    return logging.getLogger(name)


def make_session(
    *, retries: int = 4, backoff: float = 1.0, timeout: int = 120
) -> requests.Session:
    """A requests Session that rides out transient connection dropouts.

    Retries on connect/read errors and 429/5xx with exponential backoff, so a
    flaky local render service or GHL hiccup doesn't stall the core loop.
    """
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST", "PUT"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # Stash a default timeout the callers can read.
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_disk_space(path: str | Path, min_free_mb: int = 512) -> None:
    """Raise if the target volume is too full to safely write media."""
    target = Path(path)
    probe = target if target.exists() else target.parent
    free_mb = shutil.disk_usage(probe).free // (1024 * 1024)
    if free_mb < min_free_mb:
        raise OSError(
            f"Low disk space: {free_mb} MB free at {probe}, need >= {min_free_mb} MB. "
            f"Refusing to start a render that can't be written."
        )


# --- Env-driven configuration (no secrets committed) ---


@dataclass
class GenerationConfig:
    ollama_base_url: str = field(default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1:8b"))
    # Image backend: "a1111" (Automatic1111 / Forge) or "comfyui".
    image_backend: str = field(default_factory=lambda: os.getenv("IMAGE_BACKEND", "a1111"))
    a1111_base_url: str = field(default_factory=lambda: os.getenv("A1111_BASE_URL", "http://127.0.0.1:7860"))
    comfyui_base_url: str = field(default_factory=lambda: os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188"))
    output_root: str = field(default_factory=lambda: os.getenv("CREATIVE_OUTPUT_ROOT", "runs"))


@dataclass
class GHLConfig:
    token: str = field(default_factory=lambda: os.getenv("GHL_PRIVATE_TOKEN", ""))
    location_id: str = field(default_factory=lambda: os.getenv("GHL_LOCATION_ID", ""))
    # Comma-separated social account ids the post should publish to.
    account_ids: list[str] = field(
        default_factory=lambda: [a for a in os.getenv("GHL_ACCOUNT_IDS", "").split(",") if a]
    )
    base_url: str = "https://services.leadconnectorhq.com"
    api_version: str = "2021-07-28"  # GHL v2 requires this header.

    def require(self) -> None:
        missing = [
            name
            for name, val in (
                ("GHL_PRIVATE_TOKEN", self.token),
                ("GHL_LOCATION_ID", self.location_id),
                ("GHL_ACCOUNT_IDS", self.account_ids),
            )
            if not val
        ]
        if missing:
            raise EnvironmentError(f"Missing required GHL env vars: {', '.join(missing)}")
