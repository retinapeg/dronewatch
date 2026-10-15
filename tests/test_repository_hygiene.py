"""Offline artifact policy checks: inspect Git path metadata, never file contents.

The generated-data boundary is the repository's designated output directories;
filenames alone cannot establish whether arbitrary media are a real dataset.
"""
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATHS = tuple(
    f"local/history.{extension}{sidecar}"
    for extension in ("db", "sqlite", "sqlite3")
    for sidecar in ("", "-wal", "-shm", "-journal")
)
GENERATED_PATHS = (
    "__pycache__/main.cpython-311.pyc",
    "tests/__pycache__/test_main.cpython-311.pyc",
    "dronewatch/old.pyc",
    "dronewatch/old.pyo",
    ".pytest_cache/v/cache/nodeids",
    ".venv/lib/python3.11/site-packages/example.py",
    "venv/bin/python",
    ".DS_Store",
    "docs/.DS_Store",
    "local/server.log",
    "data/generated/scenario/seed-000042/observations.jsonl",
    "data/generated/camera-media/clip.mp4",
    "data/viso_synthetic/clip.mp4",
    "data/synthetic/observations.jsonl",
    "data/synthetic/ground_truth.json",
    "data/synthetic/runs/scenario/metadata.json",
)
EVIDENCE_PATHS = (
    "tests/fixtures/viso/synthetic.json",
    "tests/fixtures/observations.jsonl",
    "tests/fixtures/frame.png",
    "tests/fixtures/clip.mp4",
    "data/manifests/dataset.json",
    "data/manifests/dataset.sha256",
    "data/manifests/LICENSE.txt",
    "data/synthetic/manifests/scenario.json",
    "data/synthetic/fixtures/observation.json",
    "data/synthetic/README.md",
    "docs/results/sensor_loss_quick.json",
    "docs/results/sensor_loss_quick.md",
    "docs/images/architecture.svg",
    "docs/images/operator-preview-radar-outage.png",
    "static/drone-types.png",
    "dronewatch/synthetic/generate.py",
    "index.html",
)


def git_paths(*args, paths=None):
    """Use NUL-delimited names, including for paths containing whitespace.

    Disable user-wide ignores so these checks measure repository policy.
    Neither command opens the contents of the supplied/tracked paths.
    """
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=/dev/null", *args],
        cwd=ROOT,
        input=None if paths is None else "\0".join(paths) + "\0",
        text=True,
        capture_output=True,
        check=False,
    )
    allowed_codes = (0, 1) if args[0] == "check-ignore" else (0,)
    assert result.returncode in allowed_codes, result.stderr
    return set(result.stdout.rstrip("\0").split("\0")) if result.stdout else set()


def artifact_reason(filename):
    """Independent filename policy also catches force-added ignored artifacts."""
    path = PurePosixPath(filename)
    if set(path.parts[:-1]) & {"__pycache__", ".pytest_cache", ".venv", "venv"}:
        return "local cache or environment"
    if path.name == ".DS_Store" or path.suffix in {".pyc", ".pyo", ".log"}:
        return "generated local metadata or output"
    if any(fnmatchcase(path.name, pattern) for pattern in (
        "*.db", "*.db-*", "*.sqlite", "*.sqlite3",
        "*.sqlite-wal", "*.sqlite-shm", "*.sqlite-journal",
        "*.sqlite3-wal", "*.sqlite3-shm", "*.sqlite3-journal",
    )):
        return "local SQLite database or sidecar"
    if any(filename.startswith(prefix) for prefix in (
        "data/generated/", "data/viso_synthetic/", "data/synthetic/runs/",
    )):
        return "generated bulk data"
    if path.parent == PurePosixPath("data/synthetic") and path.suffix in {".json", ".jsonl"}:
        return "generated synthetic data"
    return None


@pytest.mark.parametrize("filename", SQLITE_PATHS)
def test_local_sqlite_files_and_sidecars_are_ignored(filename):
    assert git_paths("check-ignore", "--no-index", "-z", "--stdin", paths=[filename]) == {filename}


def test_caches_and_generated_data_are_ignored():
    assert git_paths("check-ignore", "--no-index", "-z", "--stdin", paths=GENERATED_PATHS) == set(GENERATED_PATHS)


def test_fixtures_manifests_summaries_and_runtime_images_remain_includable():
    assert not git_paths("check-ignore", "--no-index", "-z", "--stdin", paths=EVIDENCE_PATHS)
    assert all(artifact_reason(filename) is None for filename in EVIDENCE_PATHS)


@pytest.mark.parametrize("filename", SQLITE_PATHS + GENERATED_PATHS)
def test_tracked_artifact_policy_detects_prohibited_paths(filename):
    # Exercise the guard even when today's index contains no prohibited paths.
    assert artifact_reason(filename) is not None


def test_git_tracks_no_prohibited_artifacts():
    tracked = git_paths("ls-files", "-z")
    assert "index.html" in tracked, "Expected the DroneWatch index, not an empty repository"
    prohibited = {name: reason for name in sorted(tracked) if (reason := artifact_reason(name))}
    assert not prohibited, f"Proposed removals require owner review: {prohibited}"
