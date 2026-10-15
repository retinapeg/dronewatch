"""Local Viso settings; these are not a verified vendor authentication contract."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

VISO_API_KEY_ENV = "VISO_API_KEY"
VISO_WEBHOOK_SECRET_ENV = "VISO_WEBHOOK_SECRET"
LEGACY_WEBHOOK_SECRET_ENV = "DRONEWATCH_WEBHOOK_SECRET"
ALIAS_CONFLICT = (
    "Conflicting VISO_WEBHOOK_SECRET and DRONEWATCH_WEBHOOK_SECRET settings; "
    "protected ingestion disabled."
)


@dataclass(frozen=True)
class VisoConfig:
    api_key: str | None = field(default=None, repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    configuration_error: str | None = None

    @property
    def outbound_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def inbound_configured(self) -> bool:
        return bool(self.webhook_secret) and self.configuration_error is None


def read_viso_config(environ: Mapping[str, str] | None = None) -> VisoConfig:
    """Read only named settings, with no file loading or credential discovery.

    Conflicting inbound aliases fail closed while leaving the independent
    outbound setting visible. Never include setting values in diagnostics.
    """
    values = os.environ if environ is None else environ
    api_key = values.get(VISO_API_KEY_ENV, "").strip() or None
    preferred = values.get(VISO_WEBHOOK_SECRET_ENV, "").strip() or None
    legacy = values.get(LEGACY_WEBHOOK_SECRET_ENV, "").strip() or None
    if preferred and legacy and preferred != legacy:
        return VisoConfig(api_key=api_key, configuration_error=ALIAS_CONFLICT)
    return VisoConfig(api_key=api_key, webhook_secret=preferred or legacy)
