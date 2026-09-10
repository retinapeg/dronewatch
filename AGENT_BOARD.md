# DroneWatch Engineering Board

## Current mission
Deliver a deterministic five-target synthetic situational-awareness demo that works by touch at 360, 393 and 412 CSS pixels and on desktop. Preserve the Viso ingestion boundary without claiming verified Viso connectivity. User authorises frontend changes, local installs, isolated engineering, commits and routine decisions.

## Baseline
- GitHub `origin/main`: `31a32e1764572837ff43691b50aa3a15bc458714`.
- Fresh clone in this task workspace. Older `Documents/ChatGPT/DRONEWATCH` and its unpushed V0.2 candidate remain untouched.
- Python 3.11/FastAPI/SQLite; vanilla HTML/CSS/JS; no frontend build or browser suite.
- Initial execution: 10 Python tests and 10 Node tests pass. Original HTTP `/`, `/health`, `/api/config`, `/api/events` return 200 on loopback port 8765.
- Initial dependencies install successfully. One upstream anyio deprecation warning.

## Current release blockers
- No mobile browser evidence yet; QA reproducing original behaviour.
- Original demo controls hidden unless server simulation enabled; video depends on separate local service.
- Original view is one event-derived track, not the required deterministic small scenario.
- Legacy unauthenticated ingestion, raw payload API and malformed input require review.

## Assignments / branches
| Engineer | Worktree sibling | Branch | Owned work |
|---|---|---|---|
| Manager | dronewatch | agent/integration | integration, board, CLI runner, README, report |
| Codex frontend | dronewatch-mobile | codex/android-fix | operator UI, scenario, frontend tests |
| Codex QA | dronewatch-qa | codex/mobile-regressions | original screenshots, Playwright, mobile regressions |
| Codex CLI + supervising engineer | dronewatch-backend | codex/demo-boundary | ingestion boundary, Python tests, demo/test scripts |
| Claude Code | dronewatch-claude | claude/android-review | independent attacks, review evidence, competing fixes |

## Team protocol
Read this board and current Git state before work. One physical worktree per engineer. Commit explicit owned paths only. Send findings and SHA to manager. Cross-review committed diffs. Manager runs tests and browser checks before integration. Never force-push main, commit secrets, or claim physical Android testing from emulation.

## Decisions
- Keep original frontend available as a legacy page, with its helper tests preserved.
- Default new demo runs locally without external services. Scenario positions and priorities are illustrative; real events do not acquire fabricated motion.
- Use installed authenticated subscriptions: Codex CLI 0.151.0, Claude Code 2.1.267. No new paid API setup.
- Rote local/public search found no matching orchestration play; runtime requires personal login. Use authorised local shell tooling and durable file/Git evidence.

## Evidence / integration
Original baseline running locally. CLI job manifests and transcripts remain outside tracked source in sibling `.agent-runs/`. Reviewed findings and screenshots will be committed under `docs/`.

## Next actions
1. Commit failing mobile regression evidence.
2. Obtain Claude independent baseline findings while Codex implements.
3. Integrate UI, canonical boundary and test harness.
4. Run Claude adversarial pass on candidate; resolve issues with executable tests.
5. Reproduce clean launch, inspect screenshots, complete report and release checklist.
