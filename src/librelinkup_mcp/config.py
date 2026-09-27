"""Settings loaded from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from librelinkup_mcp.core.regions import Region

_TRUTHY = {"true", "1", "yes"}


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    email: str
    password: str = field(repr=False)
    region: Region
    langfuse_enabled: bool
    langfuse_capture_data: bool


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (defaults to os.environ). Raises ConfigError."""
    env = os.environ if env is None else env

    email = env.get("LIBRELINKUP_EMAIL", "").strip()
    password = env.get("LIBRELINKUP_PASSWORD", "")
    missing = [
        name
        for name, value in (("LIBRELINKUP_EMAIL", email), ("LIBRELINKUP_PASSWORD", password))
        if not value
    ]
    if missing:
        raise ConfigError(f"Missing required environment variable(s): {', '.join(missing)}")

    region_name = env.get("LIBRELINKUP_REGION", "").strip() or "US"
    try:
        region = Region.from_name(region_name)
    except ValueError:
        valid = ", ".join(member.name for member in Region)
        raise ConfigError(
            f"Invalid LIBRELINKUP_REGION {region_name!r}. Valid regions: {valid}"
        ) from None

    langfuse_enabled = bool(
        env.get("LANGFUSE_PUBLIC_KEY", "").strip() and env.get("LANGFUSE_SECRET_KEY", "").strip()
    )
    capture = env.get("LANGFUSE_CAPTURE_DATA", "").strip().lower() in _TRUTHY

    return Settings(
        email=email,
        password=password,
        region=region,
        langfuse_enabled=langfuse_enabled,
        langfuse_capture_data=capture,
    )
