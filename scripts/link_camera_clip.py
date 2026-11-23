#!/usr/bin/env python3
r"""Link a camera clip to a moment of the operator replay.

The operator view plays a linked clip while the replay is inside the clip's
window, and shows a Viso Now result for that clip against the same moment. This
script copies the clip into the camera media folder and records the link in that
folder's manifest.json.

    # list the camera's looks: when it is settled on which contacts
    python scripts/link_camera_clip.py --list-cues

    # link a clip to the first look (or the second, third, ...)
    python scripts/link_camera_clip.py /path/to/clip.mp4 --look 1 \
        --recorded "Recorded test footage (public dataset)"

    # or to the first look that has contact DW-003 in it
    python scripts/link_camera_clip.py /path/to/clip.mp4 --cue DW-003

    # or give the window in simulation seconds
    python scripts/link_camera_clip.py /path/to/clip.mp4 --start 12.6 --end 18.2

Nothing is sent anywhere. The clip still has to be analysed by Viso Now for a
result to appear; this only says which moment of the replay the clip belongs to.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def looks_from(cues: list[dict]) -> list[dict]:
    """Each unbroken spell of the camera settled on one group of contacts.

    The contacts of a look are the ones the camera picked up during it. The time
    the camera spends turning towards a group is not part of the look: a clip
    linked to a look starts when the camera has arrived. A spell in which the
    camera found nothing is not a look.
    """
    looks: list[dict] = []
    step = cues[1]["t"] - cues[0]["t"] if len(cues) > 1 else 1.0
    for index, cue in enumerate(cues):
        targets = list(cue.get("targets") or ([cue["target"]] if cue.get("target") else []))
        end = cues[index + 1]["t"] if index + 1 < len(cues) else round(cue["t"] + step, 2)
        if not targets or cue.get("settled") is False:
            continue
        last = looks[-1] if looks else None
        # A look that only loses members (contacts the radar has picked up again) is the same look.
        if last and set(targets) <= set(last["targets"]) and last["end"] == cue["t"]:
            last["end"] = end
        else:
            looks.append({"target": cue.get("target") or targets[0], "targets": targets,
                          "start": cue["t"], "end": end})
    return looks


def cue_windows(scenario: str, seed: int, count: int, mode: str) -> list[dict]:
    """The camera's looks in one replay, in order."""
    from dronewatch.api import preview

    data = preview.get_tracks(name=scenario, seed=seed, count=count,
                              duration_s=preview.OPERATOR_DEMO_DURATION_S, mode=mode)
    camera = next((s for s in data.get("sensors", []) if s.get("kind") == "eo-camera"), None)
    return looks_from(camera.get("cues", [])) if camera else []


def clip_duration(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.strip()
        value = float(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return round(value, 3) if 0 < value <= 300 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", nargs="?", type=Path, help="an .mp4 clip to link")
    parser.add_argument("--look", type=int, metavar="N", help="link to the Nth look (see --list-cues)")
    parser.add_argument("--cue", help="contact ID; uses the first look that has it in view")
    parser.add_argument("--start", type=float, help="window start, simulation seconds")
    parser.add_argument("--end", type=float, help="window end, simulation seconds")
    parser.add_argument("--recorded", metavar="NOTE",
                        help="mark the clip as recorded footage, with a short note shown under it")
    parser.add_argument("--result-after", type=float, default=3.0, metavar="SECONDS",
                        help="how far into the window the Viso Now result is shown (default 3)")
    parser.add_argument("--scenario", default="operator_demo")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--mode", default="radar_off_30s_viso")
    parser.add_argument("--media-dir", type=Path, help="defaults to the server's camera media folder")
    parser.add_argument("--list-cues", action="store_true")
    args = parser.parse_args(argv)

    wanted = args.list_cues or args.cue or args.look is not None
    windows = cue_windows(args.scenario, args.seed, args.count, args.mode) if wanted else []
    if args.list_cues:
        for number, window in enumerate(windows, start=1):
            print(f"look {number}  T+{window['start']:g} to T+{window['end']:g} s  {', '.join(window['targets'])}")
        return 0
    if args.clip is None:
        parser.error("give a clip to link, or --list-cues")
    clip = args.clip.expanduser()
    if not clip.is_file():
        parser.error(f"there is no file at {clip}")
    if clip.suffix.lower() != ".mp4":
        parser.error(f"{clip} is not an .mp4 file")

    if args.look is not None:
        if not 1 <= args.look <= len(windows):
            parser.error(f"this replay has {len(windows)} looks; try --list-cues")
        window = windows[args.look - 1]
        start, end = window["start"], window["end"]
    elif args.cue:
        window = next((w for w in windows if args.cue in w["targets"]), None)
        if window is None:
            parser.error(f"the camera never has {args.cue} in a look in this replay; try --list-cues")
        start, end = window["start"], window["end"]
    elif args.start is not None and args.end is not None:
        start, end = args.start, args.end
    else:
        parser.error("give --look N, --cue CONTACT, or both --start and --end")
    if not 0 <= start < end <= 300:
        parser.error("the window must satisfy 0 <= start < end <= 300")
    if not args.result_after >= 0:
        parser.error("--result-after cannot be negative")

    if args.media_dir:
        media = args.media_dir.expanduser().resolve()
    else:
        from dronewatch.api.camera import media_directory
        media = media_directory()
    media.mkdir(parents=True, exist_ok=True)
    target = media / clip.name
    if clip.resolve() != target.resolve():
        shutil.copyfile(clip, target)

    manifest_path = media / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    if not isinstance(manifest, dict) or not isinstance(manifest.get("clips"), list):
        manifest = {"schema_version": 1, "clips": []}
    entry = {
        "file": clip.name, "scenario": args.scenario, "seed": args.seed, "count": args.count,
        "mode": args.mode, "sim_start_s": start, "sim_end_s": end, "frame": "LOCAL_SIM_METRES",
        "playback": "realtime", "synthetic": args.recorded is None,
        # The result is shown part-way through the look, after a few seconds of footage.
        "result_after_s": round(min(args.result_after, end - start), 1),
    }
    if args.recorded:
        entry["provenance"] = args.recorded[:120]
    if (duration := clip_duration(target)) is not None:
        entry["duration_seconds"] = duration
    manifest["clips"] = [c for c in manifest["clips"] if not (isinstance(c, dict) and c.get("file") == clip.name)]
    manifest["clips"].append(entry)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    print(f"Linked {clip.name} to T+{start:g} to T+{end:g} s in {media}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
