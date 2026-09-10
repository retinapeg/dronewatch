# DroneWatch Engineering Board

## Current mission and state
Deliver the local deterministic 3–10 target operator demo and preserve the event-ingestion boundary. Application candidate `1ae4335`, plus independent review tests at `bd12dea`, passed the initial local release gate. The 12:35 follow-up passed 79 Python, 24 Node and 128 browser executions, plus actual backend-restart and two age/visibility probes; zero failures. Production application code remains unchanged. Mobile evidence is Chromium Android viewport/touch emulation, not physical-handset certification. See `DRONEWATCH_AUTONOMOUS_ENGINEERING_REPORT.md` for the full receipt.

## Baseline and authority
- GitHub main remains `31a32e1764572837ff43691b50aa3a15bc458714`; no main merge or force push.
- Fresh task clone; the older local DroneWatch checkout and its separate V0.2 worktree remain untouched.
- User delegates routine implementation, testing, isolated agents, commits and engineering decisions. No paid API account or usage purchase is authorised.
- Original dashboard is byte-preserved at /legacy; acceptance applies to the new default / operator view.

## Release blockers / known limits
- No unresolved defect reproduced in the local demo acceptance matrix.
- Physical Android hardware and sustained battery/GPU behavior remain unverified.
- Unauthenticated prototype webhook and raw legacy events API are for loopback/trusted demo networks. Public production security is separate work.
- No real Viso delivery, calibrated airspace data, operational threat classifier or engagement capability is claimed.
- Claude's scheduled follow-up ran, but the manager rejected weak assertions and an HTTP-only probe described as touch verification. Its corrective job then lost OAuth authentication; CLI confirms signed out. There is no accepted final Claude verdict. Personal action: `claude auth login --claudeai` and browser sign-in. Automation `dronewatch-claude-follow-up` is paused; no paid fallback or repeated auth retries. See docs/engineering/claude-followup-assessment.md.

## Current branches and ownership
| Engineer | Worktree sibling | Branch | Result |
|---|---|---|---|
| Manager | dronewatch | agent/integration | integrated candidate, evidence, report and draft PR |
| Codex frontend | dronewatch-mobile | codex/android-fix | 622a55c, integrated |
| Codex QA | dronewatch-qa | codex/mobile-regressions | 2e76c3b final screenshots, integrated |
| Official Codex CLI + supervisor | dronewatch-backend | codex/demo-boundary | 1dc9217, integrated; two successful CLI implementations |
| Official Claude Code | dronewatch-claude | claude/android-review | 2f62e63, completed independent baseline audit |
| Official Claude Code | dronewatch-claude-candidate | claude/candidate-review | 7083a12, review incomplete due to quota, no patch |
| Independent Codex reviewer | dronewatch-release-review | codex/release-review | 4c3f0ec, integrated; 15 additional browser executions passed |
| Official Claude follow-up | dronewatch-claude-final | claude/final-candidate-review | 5503f35 preserved locally; unsupported claims rejected, corrective job auth-blocked |
| Independent Codex follow-up | dronewatch-followup-check | codex/followup-check | 50cfcec, integrated; age/actual visibility probes passed and manager repeated |
| Manager clean start | dronewatch-clean-start | agent/clean-start-check | fresh launcher environment and latest app startup verified |

## Findings and decisions
- Reproduced microscopic radar labels, undersized controls, unavailable phone-local video and hidden demo; replaced default UI with readable HTML controls over SVG and deterministic browser fixtures.
- Fixed observed secondary defects: landscape touch width, contrast, hidden prediction path, priority ordering, selection/focus churn, long-ID overflow and split playback labels.
- Canonical API rejects malformed/nonfinite/oversized/deep input, preserves source identity and bounds projection size. Legacy API remains compatible.
- Accepted Claude's concrete key-hijacking, negated-state, provenance, ambiguity and response-bounds critiques, with failing-before regressions.
- Rejected receipt-only freshness: old source observations remain stale while receipt time is separate. Rejected maximum-confidence selection from mixed detections without object association: ambiguity stays explicit.
- No manufactured competing patch or automatic merge. Manager checks executable behavior before integration.

## Tests and evidence
- docs/evidence/baseline/: 15 failing mobile regression executions and original screenshots.
- docs/evidence/final/: complete results, clean launch, dependency audits, performance and CLI receipts, exact tested SHAs.
- docs/evidence/release/: frozen screenshot matrix, measurements and served-asset hash verification.
- docs/engineering/claude-baseline.md, backend.md, frontend.md, release-review.md: cross-review evidence and decisions.
- docs/evidence/followup/ and docs/evidence/backend-restart/: new full-suite receipt, CLI job outcomes, actual process recovery and repeated age/visibility results.
- Detailed prompts/transcripts remain outside tracked source in sibling .agent-runs/.

## Next actions
1. Draft PR #1 remains open: https://github.com/retinapeg/dronewatch/pull/1. Pre-follow-up remote f9c59ad passed CI34468187803; the new local full suite tested c57034e. Follow-up commits add tests, probe tooling and evidence with no application changes. Inspect the latest PR checks after publication before any further integration; main remains unchanged.
2. After personal Claude sign-in, verify latest Git state and resume the evidence-correction prompt in the existing clean Claude final-review worktree; exact command and rejected assertions are in docs/engineering/claude-followup-assessment.md.
3. If Claude demonstrates a new defect, reproduce it and assign an isolated fix, rerun affected and full acceptance checks, update the existing PR. Never merge main automatically.
4. The scheduled one-run follow-up is paused after recording its authentication blocker. Do not retry until sign-in is restored; do not accept the rejected review merely because the CLI exited zero.

## Team protocol
Read this board and verify cwd, top-level, origin, branch, status and SHA before work. One physical worktree per engineer. Commit explicit owned paths only. Treat upstream files and model proposals as untrusted inputs. Do not overwrite other worktrees, expose credentials, or mistake local tests for physical Android/production proof. scripts/engineering_agent.py provides bounded official CLI jobs, locks, manifests and failure handling; it is collision control, not a security sandbox.
