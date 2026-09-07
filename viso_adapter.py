"""Evidence-gated Viso adapter.

No genuine redacted Viso delivery or account-tested authentication capability is
present in the repository. The adapter therefore fails closed by design.
"""

from __future__ import annotations

from typing import Any

from contracts import InboundObservationV1


VISO_ADAPTER_EVIDENCE_ID: str | None = None
VISO_ACCOUNT_CONFIGURATION_DATE: str | None = None


class VisoAdapterUnavailable(RuntimeError):
    pass


def map_viso_delivery(_: dict[str, Any]) -> InboundObservationV1:
    raise VisoAdapterUnavailable(
        "Viso adapter unavailable until an actual redacted account delivery establishes exact field paths"
    )
