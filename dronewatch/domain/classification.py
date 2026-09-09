"""Classification as a probability distribution.

A track never carries a single categorical label. `top_class` exists for display
convenience only and must not replace the distribution anywhere that reasons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

from .enums import ObjectClass

TOLERANCE = 1e-6


@dataclass(frozen=True)
class ClassificationDistribution:
    """An explicitly normalised distribution over apparent object classes.

    Construct through `from_scores` (which normalises) or `normalised` (which
    requires an already-normalised mapping). The direct constructor validates
    rather than silently repairing, so normalisation is always explicit.
    """

    entries: Tuple[Tuple[ObjectClass, float], ...]

    def __post_init__(self) -> None:
        seen = set()
        total = 0.0
        for object_class, probability in self.entries:
            if not isinstance(object_class, ObjectClass):
                raise TypeError(f"not an ObjectClass: {object_class!r}")
            if object_class in seen:
                raise ValueError(f"duplicate class in distribution: {object_class}")
            seen.add(object_class)
            if not 0.0 <= probability <= 1.0:
                raise ValueError(
                    f"probability for {object_class.value} out of range: {probability}"
                )
            total += probability
        if abs(total - 1.0) > TOLERANCE:
            raise ValueError(f"distribution must sum to 1.0, got {total}")

    # -- construction ------------------------------------------------------

    @classmethod
    def unknown(cls) -> "ClassificationDistribution":
        """All mass on UNKNOWN. The correct answer when evidence is insufficient."""
        return cls(entries=((ObjectClass.UNKNOWN, 1.0),))

    @classmethod
    def normalised(cls, mapping: Mapping[ObjectClass, float]) -> "ClassificationDistribution":
        """Build from a mapping that is already a distribution."""
        return cls(entries=tuple(sorted(mapping.items(), key=lambda kv: kv[0].value)))

    @classmethod
    def from_scores(cls, scores: Mapping[ObjectClass, float]) -> "ClassificationDistribution":
        """Normalise non-negative scores into a distribution.

        Empty or all-zero evidence yields UNKNOWN rather than a fabricated guess.
        """
        for object_class, score in scores.items():
            if score < 0:
                raise ValueError(f"negative score for {object_class}: {score}")
        total = sum(scores.values())
        if total <= 0:
            return cls.unknown()
        return cls.normalised({key: value / total for key, value in scores.items()})

    # -- reading -----------------------------------------------------------

    def as_dict(self) -> Dict[ObjectClass, float]:
        return dict(self.entries)

    def probability(self, object_class: ObjectClass) -> float:
        return self.as_dict().get(object_class, 0.0)

    def top(self) -> Tuple[ObjectClass, float]:
        """Derived convenience only. Never store this in place of the distribution."""
        return max(self.entries, key=lambda kv: (kv[1], kv[0].value))

    @property
    def top_class(self) -> ObjectClass:
        return self.top()[0]

    @property
    def top_probability(self) -> float:
        return self.top()[1]

    def is_uninformative(self, threshold: float = 0.5) -> bool:
        """True when UNKNOWN holds at least `threshold` of the mass."""
        return self.probability(ObjectClass.UNKNOWN) >= threshold
