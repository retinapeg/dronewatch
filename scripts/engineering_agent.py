#!/usr/bin/env python3
"""Run one bounded engineer job in an isolated DroneWatch worktree.

No scheduler, automatic integration, publication, or credential provisioning.
The manager reviews commits and executable evidence before integration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", choices=["claude", "codex"])
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    worktree = args.worktree.resolve()
    output = args.output.resolve()
    if git(worktree, "rev-parse", "--show-toplevel") != str(worktree):
        raise SystemExit("Worktree root mismatch")
    if git(worktree, "remote", "get-url", "origin") not in {
        "https://github.com/retinapeg/dronewatch.git",
        "git@github.com:retinapeg/dronewatch.git",
    }:
        raise SystemExit("Unexpected repository origin")
    branch = git(worktree, "branch", "--show-current")
    if not branch or branch in {"main", "master"}:
        raise SystemExit("Engineer must use an isolated named branch")
    output.mkdir(parents=True, exist_ok=True)
    # Lock lives in the worktree's own Git directory, never the shared common dir.
    lock = Path(git(worktree, "rev-parse", "--absolute-git-dir")) / "engineering-job.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SystemExit(f"Another engineer owns this worktree; inspect {lock}")
    os.write(lock_fd, str(os.getpid()).encode())
    os.close(lock_fd)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = output / f"{stamp}-{args.engine}"
    prompt = args.prompt.read_text()
    common = (
        "Work only in the assigned worktree. Read its engineering board if present. "
        "Never push, change main, delete unrelated files, read credentials, or edit other "
        "worktrees. Network access is only for official dependency/documentation retrieval "
        "if required. Do not call external paid APIs. Commit only your owned paths. "
        "Return concrete findings with commands, results and commit SHA; do not claim a "
        "test you did not execute. Synthetic demonstration only, no weapon engagement.\n\n"
    )
    if args.engine == "claude":
        command = [
            "claude", "--print", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
            "--disallowedTools", "Bash(git push*)",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands", "--no-chrome",
        ]
    else:
        command = [
            "codex", "--ask-for-approval", "never", "exec",
            "--sandbox", "workspace-write", "--json",
            "--add-dir", git(worktree, "rev-parse", "--git-common-dir"),
            "--output-last-message", str(prefix) + ".final.md", "-",
        ]
    env = os.environ.copy()
    # Use existing subscription sessions; do not silently switch to metered API keys.
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY"):
        env.pop(key, None)
    metadata = {
        "engine": args.engine, "worktree": str(worktree), "branch": branch,
        "base_sha": git(worktree, "rev-parse", "HEAD"), "started_at": stamp,
        "command": command, "timeout_seconds": args.timeout,
    }
    manifest = Path(str(prefix) + ".manifest.json")
    manifest.write_text(json.dumps(metadata, indent=2) + "\n")
    Path(str(prefix) + ".prompt.md").write_text(common + prompt)
    process = None
    started = time.monotonic()
    try:
        with open(str(prefix) + ".stdout.jsonl", "w") as stdout, open(str(prefix) + ".stderr.log", "w") as stderr:
            process = subprocess.Popen(command, cwd=worktree, env=env, stdin=subprocess.PIPE,
                                       stdout=stdout, stderr=stderr, text=True, start_new_session=True)
            print(json.dumps({"status": "running", "pid": process.pid, "manifest": str(manifest)}), flush=True)
            try:
                process.communicate(common + prompt, timeout=args.timeout)
                metadata["exit_code"] = process.returncode
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                metadata["exit_code"] = 124
                metadata["status"] = "timed_out"
    except BaseException:
        if process and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        raise
    finally:
        metadata["elapsed_seconds"] = round(time.monotonic() - started, 2)
        metadata["final_sha"] = git(worktree, "rev-parse", "HEAD")
        manifest.write_text(json.dumps(metadata, indent=2) + "\n")
        lock.unlink(missing_ok=True)
    print(json.dumps(metadata), flush=True)
    return int(metadata["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
