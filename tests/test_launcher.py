"""./run starts the demo with one command from any folder, and never prints the webhook secret."""
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run"
SECRET = "launcher-test-value-123"


@pytest.fixture
def checkout(tmp_path):
    """A stand-in checkout: the real launcher, and a fake server that reports what it was given."""
    shutil.copy(RUN, tmp_path / "run")
    server = tmp_path / ".venv" / "bin" / "uvicorn"
    server.parent.mkdir(parents=True)
    server.write_text('#!/bin/sh\necho "server args: $*"\necho "server secret: ${DRONEWATCH_WEBHOOK_SECRET:-none}" > secret-seen.txt\n')
    server.chmod(0o755)
    return tmp_path


def start(folder, *args, cwd=None, **env):
    clean = {k: v for k, v in os.environ.items() if k not in ("DRONEWATCH_WEBHOOK_SECRET", "VISO_WEBHOOK_SECRET", "PORT")}
    return subprocess.run([str(folder / "run"), "--no-pull", "--no-open", *args], cwd=cwd or folder,
                          env={**clean, **env}, capture_output=True, text=True, timeout=30)


def test_launcher_is_executable_and_parses_in_a_plain_shell():
    assert RUN.stat().st_mode & stat.S_IXUSR
    tracked = subprocess.run(["git", "ls-files", "-s", "run"], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked.startswith("100755"), "run must be committed as executable"
    # macOS ships an old bash; the script sticks to what a plain POSIX shell accepts.
    assert subprocess.run(["sh", "-n", str(RUN)], capture_output=True).returncode == 0


def test_it_works_from_another_folder_and_starts_the_server_on_the_local_address(checkout, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    result = start(checkout, cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert "server args: main:app --host 127.0.0.1 --port 8000" in result.stdout
    assert "http://127.0.0.1:8000/preview?demo=viso" in result.stdout
    assert (checkout / "secret-seen.txt").read_text().strip() == "server secret: none"
    assert "secret: not set" in result.stdout


def test_the_secret_comes_from_the_private_file_and_is_never_printed(checkout):
    (checkout / ".env.local").write_text(f'# local only\nOTHER=1\nDRONEWATCH_WEBHOOK_SECRET="{SECRET}"\n')
    result = start(checkout, PORT="8123")
    assert result.returncode == 0, result.stderr
    assert (checkout / "secret-seen.txt").read_text().strip() == f"server secret: {SECRET}"
    assert "secret: set" in result.stdout and "--port 8123" in result.stdout
    assert SECRET not in result.stdout + result.stderr


def test_an_exported_secret_wins_over_the_file(checkout):
    (checkout / ".env.local").write_text("DRONEWATCH_WEBHOOK_SECRET=from-the-file\n")
    start(checkout, DRONEWATCH_WEBHOOK_SECRET=SECRET)
    assert (checkout / "secret-seen.txt").read_text().strip() == f"server secret: {SECRET}"


def test_an_unknown_option_or_a_missing_environment_stops_with_a_plain_message(checkout):
    assert start(checkout, "--wat").returncode == 2
    shutil.rmtree(checkout / ".venv")
    result = start(checkout)
    assert result.returncode == 1 and "python3 -m venv .venv" in result.stdout


@pytest.fixture
def tools(tmp_path_factory):
    """Stand-ins for cloudflared and the macOS clipboard, first on the PATH."""
    folder = tmp_path_factory.mktemp("tools")
    tunnel = folder / "cloudflared"
    tunnel.write_text('#!/bin/sh\necho "$$" > "$SEEN/tunnel.pid"\necho "$*" > "$SEEN/tunnel.args"\n'
                      'echo "INF Requesting new quick Tunnel on https://api.trycloudflare.com/tunnel" >&2\n'
                      'echo "INF |  https://quiet-river-demo.trycloudflare.com  |" >&2\nexec sleep 30\n')
    clipboard = folder / "pbcopy"
    clipboard.write_text('#!/bin/sh\ncat > "$SEEN/clipboard"\n')
    for tool in (tunnel, clipboard):
        tool.chmod(0o755)
    return folder


def viso(checkout, tools, **env):
    return start(checkout, "--viso", PATH=f"{tools}{os.pathsep}{os.environ['PATH']}", SEEN=str(tools), **env)


def test_viso_makes_a_secret_opens_a_tunnel_and_puts_the_webhook_address_on_the_clipboard(checkout, tools):
    result = viso(checkout, tools, PORT="8124")
    assert result.returncode == 0, result.stderr
    made = (checkout / ".env.local").read_text().strip()
    assert made.startswith("DRONEWATCH_WEBHOOK_SECRET=") and stat.S_IMODE((checkout / ".env.local").stat().st_mode) == 0o600
    secret = made.split("=", 1)[1]
    assert len(secret) == 40 and secret.isalnum()
    # The server got the secret, the tunnel points at the server, and the clipboard holds the whole address.
    assert (checkout / "secret-seen.txt").read_text().strip() == f"server secret: {secret}"
    assert (tools / "tunnel.args").read_text().strip() == "tunnel --url http://127.0.0.1:8124"
    assert (tools / "clipboard").read_text() == f"https://quiet-river-demo.trycloudflare.com/v2/webhook/viso?token={secret}"
    # The screen shows where Viso Now reaches this computer, and never the secret.
    assert "https://quiet-river-demo.trycloudflare.com/v2/webhook/viso\n" in result.stdout
    assert "on the clipboard" in result.stdout and secret not in result.stdout + result.stderr
    # When the server stops, the tunnel is stopped with it.
    with pytest.raises(ProcessLookupError):
        os.kill(int((tools / "tunnel.pid").read_text()), 0)


def test_viso_keeps_a_secret_that_is_already_there(checkout, tools):
    (checkout / ".env.local").write_text(f"DRONEWATCH_WEBHOOK_SECRET={SECRET}\n")
    result = viso(checkout, tools)
    assert result.returncode == 0, result.stderr
    assert (checkout / ".env.local").read_text() == f"DRONEWATCH_WEBHOOK_SECRET={SECRET}\n"
    assert (tools / "clipboard").read_text().endswith(f"/v2/webhook/viso?token={SECRET}")
    assert SECRET not in result.stdout + result.stderr


def test_viso_without_cloudflared_says_how_to_install_it_and_starts_nothing(checkout, tmp_path_factory):
    bare = tmp_path_factory.mktemp("bare")          # a PATH with the shell's basics and no cloudflared
    for name in ("sh", "bash", "dirname", "sed", "head", "tr", "git", "cut", "env", "sleep", "cat"):
        if found := shutil.which(name):
            (bare / name).symlink_to(found)
    result = start(checkout, "--viso", PATH=str(bare))
    assert result.returncode == 1 and "brew install cloudflared" in result.stdout
    assert not (checkout / "secret-seen.txt").exists() and not (checkout / ".env.local").exists()

