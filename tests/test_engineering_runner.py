"""Exercise orchestration failure handling with an explicitly fake CLI fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "engineering_agent.py"


@pytest.fixture
def job(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "engineer/test", str(repo)], check=True, capture_output=True)
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("config", "user.name", "Runner Test")
    git("config", "user.email", "runner@example.invalid")
    git("remote", "add", "origin", "https://github.com/retinapeg/dronewatch.git")
    git("commit", "--allow-empty", "-m", "fixture")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Explicit fake CLI test; no model is invoked.")
    binary = tmp_path / "bin"
    binary.mkdir()
    fake = binary / "claude"
    output = tmp_path / "output"
    def run(body, timeout=5):
        fake.write_text(f"#!{sys.executable}\nimport sys,json,time\nsys.stdin.read()\n{body}\n")
        fake.chmod(0o700)
        return subprocess.run(
            [sys.executable, str(RUNNER), "claude", "--worktree", str(repo),
             "--prompt", str(prompt), "--output", str(output), "--timeout", str(timeout)],
            env={**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"]},
            text=True, capture_output=True, timeout=20,
        )
    return repo, output, git, run


def test_refuses_main_without_invoking_model(job):
    repo, output, git, run = job
    git("branch", "-m", "main")
    result = run("raise RuntimeError('must not execute')")
    assert result.returncode != 0
    assert "isolated named branch" in result.stderr
    assert not output.exists()


def test_refuses_concurrent_owner_without_invoking_model(job):
    repo, output, git, run = job
    lock = repo / ".git" / "engineering-job.lock"
    lock.write_text("123456789")
    result = run("raise RuntimeError('must not execute')")
    assert result.returncode != 0
    assert "Another engineer owns" in result.stderr
    assert lock.read_text() == "123456789"


def test_zero_process_exit_does_not_hide_model_failure(job):
    repo, output, git, run = job
    result = run("print(json.dumps({'type':'result','subtype':'error','is_error':True}))")
    assert result.returncode == 1
    manifest = json.loads(next(output.glob("*.manifest.json")).read_text())
    assert manifest["model_completed"] is False
    assert not (repo / ".git" / "engineering-job.lock").exists()


def test_timeout_records_failure_and_releases_worktree(job):
    repo, output, git, run = job
    result = run("time.sleep(30)", timeout=1)
    assert result.returncode == 124
    manifest = json.loads(next(output.glob("*.manifest.json")).read_text())
    assert manifest["status"] == "timed_out"
    assert manifest["model_completed"] is False
    assert manifest["elapsed_seconds"] < 10
    assert not (repo / ".git" / "engineering-job.lock").exists()
