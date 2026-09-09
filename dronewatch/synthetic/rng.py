"""Deterministic randomness.

Every stochastic decision comes from an explicit Random instance derived from
the master seed and a stable string key. Global random state is never touched,
so generation is reproducible regardless of what else the process has done.
"""
from __future__ import annotations

import hashlib
import random
from typing import Iterable


def derive_seed(master_seed: int, *parts: str) -> int:
    """Stable sub-seed from a master seed and named parts.

    Uses blake2b rather than hash(), because Python randomises string hashing
    per process and would silently break reproducibility across runs.
    """
    digest = hashlib.blake2b(digest_size=8)
    digest.update(str(master_seed).encode("utf-8"))
    for part in parts:
        digest.update(b"\x00")
        digest.update(part.encode("utf-8"))
    return int.from_bytes(digest.digest(), "big")


def stream(master_seed: int, *parts: str) -> random.Random:
    """A dedicated RNG for one named concern."""
    return random.Random(derive_seed(master_seed, *parts))


def ordered(values: Iterable[str]) -> list:
    """Deterministic iteration order for anything set-like."""
    return sorted(values)
