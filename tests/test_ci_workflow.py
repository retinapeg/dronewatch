"""Offline regression checks for the repository's CI validation commands."""
from pathlib import Path
import re

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


def run_steps():
    """Read active run steps in this workflow's fixed indentation layout.

    This deliberately checks the existing layout, rather than parsing arbitrary
    YAML or counting commands mentioned only in comments or step names.
    """
    steps = re.split(r"(?m)^      - ", WORKFLOW.read_text(encoding="utf-8"))[1:]
    commands = []
    for step in steps:
        match = re.search(r"(?m)^        run: (.+)$", step)
        if match is None:
            continue
        assert not re.search(r"(?m)^        (?:if|continue-on-error):", step), (
            "Validation steps must run unconditionally and propagate failures"
        )
        command = match.group(1)
        if command == "|":
            command = "\n".join(re.findall(r"(?m)^          (.+)$", step))
        commands.append(command)
    return commands


def test_ci_runs_all_javascript_test_files():
    # Keep the glob literal: enumerating today's files omits tomorrow's suites.
    assert "node --test tests/*.test.cjs" in run_steps()


@pytest.mark.parametrize("command", [
    "python -m pytest -q",
    "python -m compileall -q main.py demo_feed.py",
    "python -m pip_audit -r requirements.txt",
])
def test_ci_retains_python_validation_gates(command):
    assert command in run_steps()


def test_ci_installs_requirements_and_audit_tool():
    commands = "\n".join(run_steps()).splitlines()
    assert "python -m pip install -r requirements.txt" in commands
    assert any(re.fullmatch(r"python -m pip install pip-audit==\d+\.\d+\.\d+", command)
               for command in commands)
