# Engineering workflow

`AGENT_BOARD.md` is the compact current handoff. Git commits, test artifacts and reviewed screenshots establish results. The board is not a transcript.

The manager integrates on `agent/integration`. Each engineer owns a separate physical Git worktree. Branch names alone do not isolate edits. Before assigning work, inspect the repository root, origin, branch, status and commit. Never reset or clean another engineer's worktree.

## Scriptable model jobs

Both official CLIs were installed and authenticated with existing subscription sessions during bootstrap: Codex 0.151.0 and Claude Code 2.1.267. Their installed `--help` output determined syntax. No API account or paid infrastructure was created.

The manager can run a bounded task using a prompt file:

```bash
python3 scripts/engineering_agent.py claude \
  --worktree ../dronewatch-claude \
  --prompt ../.agent-runs/prompts/review.md \
  --output ../.agent-runs/review --timeout 1200

python3 scripts/engineering_agent.py codex \
  --worktree ../dronewatch-backend \
  --prompt ../.agent-runs/prompts/backend.md \
  --output ../.agent-runs/backend --timeout 1800
```

Create the worktree first from the exact review base, for example `git worktree add ../dronewatch-claude -b claude/android-review agent/integration`. Prompts must name owned paths, baseline SHA, expected evidence, and constraints. The runner rejects main/master, unexpected origin, and a second job in the same worktree. It records the base/final SHA, command, duration, process exit and model completion separately. Transcripts remain outside tracked source. Timeout stops the job's process group. A stale lock after a machine crash needs inspection of its recorded PID before removal.

Claude runs with explicit local engineering tools, no connected MCP servers, no browser-profile access, no interactive permission prompts, and a prohibition on pushing. Codex uses `--ignore-user-config` because this installation's configured model required a newer CLI; the CLI's supported default successfully provided the fallback. Codex uses the same unrestricted local execution scope the manager was authorised to use, so localhost server tests and isolated worktree commits can execute. These modes are appropriate only for reviewed local repository engineering prompts. They are not a security sandbox for arbitrary third-party prompts or repositories.

The runner removes metered API key environment variables and uses existing authenticated sessions. Authentication failure is a job blocker, not a reason to stop independent local work. Do not provision paid credentials, repeatedly launch unchanged failing jobs, or claim a job succeeded solely from process exit zero. After a failure, inspect the manifest and final result; fix the concrete cause and make one bounded retry while other useful work continues.

## Adversarial loop

1. QA reproduces defects on the original commit and records failing assertions and screenshots.
2. Codex implements a focused candidate and commits explicit owned paths.
3. Claude reads the exact candidate diff, runs attacks and tests in its own worktree, and ranks findings by observed impact.
4. Codex responds to each substantial finding with reproduction or contrary executable evidence. Competing patches are tested against the same cases when alternatives warrant implementation.
5. The manager reviews changes and integrates selected commits, then runs Python, Node and Playwright suites and inspects rendered screenshots.
6. Update the board and engineering report with what actually passed, known limits and the next concrete task.

There is no automatic merge, push, or recursive agent spawning in the runner. The manager owns those decisions. Do not launch background loops that keep spending subscription usage after the release queue is empty. New work begins from the board and verified Git state.

## Baseline protection

This task started from a fresh clone of GitHub `31a32e1`. The older local DroneWatch checkout and its separate unpushed V0.2 candidate were identified but preserved. That candidate is a separate integration decision; its past test results do not establish anything about this branch. The original dashboard is retained as `legacy.html` for historical comparison. Mobile acceptance applies to the new default operator view.
