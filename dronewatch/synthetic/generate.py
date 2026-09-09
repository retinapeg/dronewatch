"""Command-line scenario generation.

    python -m dronewatch.synthetic.generate --scenario mixed_threat_decoy \
        --seed 42 --output /tmp/dronewatch-scenario

    python -m dronewatch.synthetic.generate --scenario small_swarm \
        --seed 42 --count 10 --output /tmp/dronewatch-swarm
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .generator import DEFAULT_DURATION_S, DEFAULT_TICK_HZ, generate_scenario
from .scenarios import SCENARIO_NAMES
from .serialise import write_scenario
from .stats import describe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dronewatch.synthetic.generate",
        description="Generate a deterministic synthetic multi-sensor C-UAS scenario.",
    )
    parser.add_argument("--scenario", required=True, choices=SCENARIO_NAMES)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, default=None,
                        help="Directory root. Omit to print the summary only.")
    parser.add_argument("--count", type=int, default=None,
                        help="Entity count for small_swarm.")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--tick-hz", type=float, default=DEFAULT_TICK_HZ)
    parser.add_argument("--threat-fraction", type=float, default=0.5)
    parser.add_argument("--decoy-fraction", type=float, default=0.5)
    parser.add_argument("--list", action="store_true", help="List scenarios and exit.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list" in argv:
        for name in SCENARIO_NAMES:
            print(name)
        return 0

    args = build_parser().parse_args(argv)
    result = generate_scenario(
        args.scenario, seed=args.seed, duration_s=args.duration,
        tick_hz=args.tick_hz, count=args.count,
        threat_fraction=args.threat_fraction, decoy_fraction=args.decoy_fraction,
    )
    summary = describe(result)

    destination = None
    if args.output is not None:
        destination = write_scenario(result, args.output)

    modalities = ", ".join(sorted(summary["observations_by_modality"]))
    print(f"scenario     {summary['scenario_name']}")
    print(f"seed         {summary['seed']}")
    print(f"entities     {summary['entity_count']}")
    print(f"observations {summary['observation_count']}")
    print(f"modalities   {modalities}")
    print(f"duration     {summary['duration_s']:g} s")
    print(f"false pos.   {summary['false_positive_observations']}")
    print(f"duplicates   {summary['duplicate_observations']}")
    print(f"out of order {summary['out_of_order_observations']}")
    print(f"output       {destination if destination else '(not written)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
