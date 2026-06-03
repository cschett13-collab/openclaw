"""Shared configuration & infrastructure for the local creative engine.

The rock-solid foundation the rendering/publishing scripts build on:

  1. Environment & core paths — load/validate critical env vars and define the
     strict on-disk workspace boundaries (raw assets, rendered video, temp frames).
  2. Network & GHL metadata — standardized GoHighLevel API v2 headers and a
     centralized exponential-backoff request retrier for flaky networks.
  3. Hardware & render constraints — per-service timeouts so a local render can't
     hang the RTX 5090 host forever, plus a disk-space sentinel that raises an
     explicit DiskSpaceError before a write can fill the partition.

Self-contained and strictly typed. No filesystem or network side effects at
import time — directories are only created and checked when explicitly invoked.
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ConfigError(RuntimeError):
    """Raised when required configuration / environment is missing or invalid."""


class DiskSpaceError(OSError):
    """Raised when the asset partition is below its safety threshold."""


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

LOG_FORMAT: Final = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format=LOG_FORMAT)
    return logging.getLogger(name)


log = get_logger("config")


def _env(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val is not None and val != "" else default


# --------------------------------------------------------------------------- #
# 1. Environment & core paths
# --------------------------------------------------------------------------- #

# Default workspace root on the RTX 5090 host (Synology-style volume). Override
# with CREATIVE_ASSET_ROOT for dev boxes.
DEFAULT_ASSET_ROOT: Final = "/volume1/FVCE_Pipeline/creative_assets"


@dataclass(frozen=True)
class WorkspacePaths:
    """Strict on-disk boundaries for the pipeline's outputs."""

    root: Path
    raw: Path           # raw model output / concept JSON
    rendered: Path      # finished video files ready to publish
    temp_frames: Path   # scratch frames, safe to purge between runs

    @classmethod
    def from_env(cls) -> "WorkspacePaths":
        root = Path(_env("CREATIVE_ASSET_ROOT", DEFAULT_ASSET_ROOT)).expanduser()
        return cls(
            root=root,
            raw=root / "raw",
            rendered=root / "rendered",
            temp_frames=root / "temp_frames",
        )

    def all(self) -> tuple[Path, ...]:
        return (self.raw, self.rendered, self.temp_frames)

    def ensure(self) -> "WorkspacePaths":
        """Create the workspace tree. Call at runtime, never at import."""
        for p in self.all():
            p.mkdir(parents=True, exist_ok=True)
        return self


# --------------------------------------------------------------------------- #
# 3. Hardware & render constraints — timeouts
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Timeouts:
    """Per-service request timeouts (seconds) so nothing hangs indefinitely."""

    # Text gen is quick; local image render is slow; GHL is a remote API.
    ollama: int = field(default_factory=lambda: int(_env("OLLAMA_TIMEOUT", "120")))
    render: int = field(default_factory=lambda: int(_env("RENDER_TIMEOUT", "600")))
    ghl: int = field(default_factory=lambda: int(_env("GHL_TIMEOUT", "120")))
    connect: int = field(default_factory=lambda: int(_env("CONNECT_TIMEOUT", "10")))


TIMEOUTS: Final = Timeouts()

# Free-space floor for the asset partition before we refuse to render/write.
MIN_FREE_MB: Final = int(_env("MIN_FREE_MB", "2048"))


# --------------------------------------------------------------------------- #
# 2. Network & GHL metadata
# --------------------------------------------------------------------------- #

GHL_API_BASE: Final = "https://services.leadconnectorhq.com"
GHL_API_VERSION: Final = "2021-07-28"  # required by every GHL v2 request


@dataclass
class GHLConfig:
    token: str = field(default_factory=lambda: _env("GHL_PRIVATE_TOKEN", ""))
    location_id: str = field(default_factory=lambda: _env("GHL_LOCATION_ID", ""))
    account_ids: list[str] = field(
        default_factory=lambda: [a for a in _env("GHL_ACCOUNT_IDS", "").split(",") if a]
    )
    base_url: str = GHL_API_BASE
    api_version: str = GHL_API_VERSION

    def headers(self, *, json_body: bool = True) -> dict[str, str]:
        """Standardized GHL v2 headers (Bearer auth + Version)."""
        h = {
            "Authorization": f"Bearer {self.token}",
            "Version": self.api_version,
            "Accept": "application/json",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def require(self) -> "GHLConfig":
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
            raise ConfigError(f"Missing required GHL env vars: {', '.join(missing)}")
        return self


@dataclass
class GenerationConfig:
    ollama_base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "llama3.1:8b"))
    image_backend: str = field(default_factory=lambda: _env("IMAGE_BACKEND", "a1111"))
    a1111_base_url: str = field(default_factory=lambda: _env("A1111_BASE_URL", "http://127.0.0.1:7860"))
    comfyui_base_url: str = field(default_factory=lambda: _env("COMFYUI_BASE_URL", "http://127.0.0.1:8188"))
    paths: WorkspacePaths = field(default_factory=WorkspacePaths.from_env)
    timeouts: Timeouts = TIMEOUTS

    @property
    def output_root(self) -> str:
        """Where dated run dirs are created (kept for caller compatibility)."""
        return str(self.paths.rendered)


def validate_environment(*, require_ghl: bool = False) -> dict[str, str]:
    """Validate critical env vars. Raises ConfigError on a hard problem.

    OLLAMA_BASE_URL is always checked for a sane scheme; GHL creds are only
    enforced when require_ghl=True (so the generator can run without them).
    """
    gen = GenerationConfig()
    if not gen.ollama_base_url.startswith(("http://", "https://")):
        raise ConfigError(f"OLLAMA_BASE_URL must be an http(s) URL, got: {gen.ollama_base_url!r}")

    resolved = {
        "OLLAMA_BASE_URL": gen.ollama_base_url,
        "IMAGE_BACKEND": gen.image_backend,
        "CREATIVE_ASSET_ROOT": str(gen.paths.root),
    }
    if require_ghl:
        ghl = GHLConfig()
        ghl.require()
        resolved["GHL_LOCATION_ID"] = ghl.location_id
        resolved["GHL_PRIVATE_TOKEN"] = "***set***"
    return resolved


# --------------------------------------------------------------------------- #
# Disk helpers & sentinel
# --------------------------------------------------------------------------- #


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _first_existing(path: str | Path) -> Path:
    """Walk up to the nearest existing ancestor (so we can stat a fresh path)."""
    p = Path(path).expanduser().resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def disk_free_mb(path: str | Path) -> int:
    return shutil.disk_usage(_first_existing(path)).free // (1024 * 1024)


def disk_sentinel(path: str | Path, *, min_free_mb: int = MIN_FREE_MB) -> int:
    """Guard the asset partition. Raises DiskSpaceError below the threshold.

    Returns the free space in MB on success so callers can log headroom.
    """
    free_mb = disk_free_mb(path)
    if free_mb < min_free_mb:
        raise DiskSpaceError(
            f"Low disk space: {free_mb} MB free at {_first_existing(path)}, "
            f"need >= {min_free_mb} MB. Refusing to write to avoid filling the partition."
        )
    return free_mb


def ensure_disk_space(path: str | Path, min_free_mb: int = MIN_FREE_MB) -> None:
    """Backwards-compatible alias around disk_sentinel."""
    disk_sentinel(path, min_free_mb=min_free_mb)


# --------------------------------------------------------------------------- #
# HTTP session + centralized retrier
# --------------------------------------------------------------------------- #

_RETRYABLE_EXC: Final = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)
_RETRYABLE_STATUS: Final = frozenset({429, 500, 502, 503, 504})


def make_session(*, retries: int = 0, backoff: float = 1.0, timeout: int = TIMEOUTS.ghl) -> requests.Session:
    """A pooled requests Session.

    Connection-level retries on idempotent methods are handled by the mounted
    adapter; application-level retries (incl. POST media pushes) go through
    ``request_with_retry`` so they're logged and status-aware. Keep ``retries``
    at 0 here when you intend to use ``request_with_retry`` to avoid compounding.
    """
    session = requests.Session()
    if retries:
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            backoff_factor=backoff,
            status_forcelist=tuple(_RETRYABLE_STATUS),
            allowed_methods=frozenset({"GET", "PUT"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    timeout: int | tuple[int, int] | None = None,
    **kwargs: object,
) -> requests.Response:
    """Centralized exponential-backoff retrier for flaky networks / media pushes.

    Retries on connection drops, timeouts, and retryable 5xx/429 responses with
    jittered exponential backoff. Honors ``Retry-After`` when present. Raises the
    last exception (or returns the final response) after ``max_attempts``.
    """
    if timeout is None:
        timeout = (TIMEOUTS.connect, getattr(session, "request_timeout", TIMEOUTS.ghl))

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.request(method, url, timeout=timeout, **kwargs)  # type: ignore[arg-type]
        except _RETRYABLE_EXC as exc:
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = _backoff_delay(attempt, base_delay, max_delay)
            log.warning("%s %s failed (%s); retry %d/%d in %.1fs", method, url, exc, attempt, max_attempts, delay)
            time.sleep(delay)
            continue

        if resp.status_code in _RETRYABLE_STATUS and attempt < max_attempts:
            delay = _retry_after(resp) or _backoff_delay(attempt, base_delay, max_delay)
            log.warning("%s %s -> %d; retry %d/%d in %.1fs", method, url, resp.status_code, attempt, max_attempts, delay)
            time.sleep(delay)
            continue
        return resp

    assert last_exc is not None  # only reachable via the exception path
    raise last_exc


def _backoff_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    # Exponential growth (base * 2^(n-1)) with full jitter, clamped.
    raw = base_delay * (2 ** (attempt - 1))
    return min(max_delay, raw) * (0.5 + random.random() / 2)


def _retry_after(resp: requests.Response) -> float | None:
    val = resp.headers.get("Retry-After")
    if val and val.isdigit():
        return float(val)
    return None
