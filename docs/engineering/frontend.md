# Frontend engineering evidence

## Baseline and ownership

- Started from upstream `31a32e1` in isolated `codex/android-fix` worktree.
- Preserved upstream `index.html` verbatim as `legacy.html`; the unchanged historical helper assertions now read that file. Backend serves it at `/legacy`.
- Original baseline ran before replacement. Independent QA captured all requested mobile widths and desktop.
- Confirmed defects: radar target IDs rendered approximately 5.07–5.85 px on the requested phones; state/boundary labels about 3–4 px; controls 25–33 px; loopback video URL points at the phone itself; normal configuration hides local demo controls. QA found no baseline document-level horizontal overflow; do not claim one.

## Implementation and decisions

- Plain HTML, CSS and JavaScript; no remote fonts, video, maps, external APIs, runtime library, bundler or build step.
- Browser-owned deterministic producer in `assets/scenario.js` emits the canonical target representation. The default is five targets; operator can choose three or ten. Reset produces identical positions, IDs, priorities and confidence at the same scenario time.
- All synthetic positions use an uncalibrated unit-square schematic. Confidence is illustrative and status is scenario-authored. Physical velocity, heading and time-to-boundary are not fabricated. Course directions use the authored schematic vector and are labelled scripted.
- Semantic HTML target buttons overlay an SVG drawing. They remain 50–54 px wide and 54 px high independent of the SVG scale. Target IDs are 11 CSS px. All meaningful radar text is at least 10 CSS px.
- Selection, 1.7× bounded focus, playback, pause/resume, reset, count selection and uncertainty drill-down are available by touch and keyboard. Target buttons persist between animation frames; sensor detail focus and expanded interpretation survive polling.
- Rendering runs at four updates per second and stops scenario advancement while the document is hidden. No random values, unbounded histories or accumulating animation-frame handlers.
- `/api/targets` sensor view is separate. Missing geographic measurements and predictions stay unavailable; camera frame positions are textual context and are never drawn on the schematic. Source kind remains visible, including synthetic, test and unauthenticated webhook events.
- Target identity includes source kind, source and target ID. Different cameras with the same target ID are not merged. Invalid payloads fail closed; cached records remain visibly cached after failed refresh. Missing/unverified observation time never appears current because a webhook was just received.
- Polls use a timeout, cancellation and generation check. Old requests cannot replace a new mode's state. All external strings use text nodes; no event payload is inserted as HTML.

## Challenges accepted on evidence

- QA's first browser run: 59 passing, 8 failing, 8 intentionally skipped. Failures were readable context labels, landscape button width and panel-number contrast, not normal runtime/resource errors. Corrected all three causes.
- Manager and QA independently showed that the initial 15-second prediction was hidden below the selected button. Replaced it with the full remaining authored route, explicitly labelled "Scripted route to 01:30", and rotated arrows to match actual schematic movement. No extrapolated physical trajectory is claimed.
- Manager showed fixture array order disagreed with the priority label. The producer now sorts by priority; unit coverage verifies the order.
- QA reproduced loss of keyboard focus on the expanded sensor interpretation summary during polling. Detail recreation now restores the focused control only when the same source-scoped target remains selected.
- Manager requested laptop usability. At 1440×900, the radar is 375×375 and playback controls occupy y=807–871; they fit the initial viewport. Selected detail sits alongside the air picture, first in the side rail; the target register follows below it. Mobile remains a normal single scrolling document.

## Evidence and remaining validation

- `node --check assets/operator.js` and `node --check assets/scenario.js`: passed.
- `node --test tests/dashboard.test.cjs tests/scenario.test.cjs`: 23 passed at the initial implementation checkpoint (10 preserved legacy + 13 meaningful scenario/boundary tests).
- Initial corrected screenshots manually inspected at `/tmp/dronewatch-frontend-360.png` and `/tmp/dronewatch-frontend-1440.png`; independent QA retains tracked screenshots and reports under `docs/evidence` in the integration checkout.
- Final browser results, Claude critique, integration SHA and release outcome belong to the manager's release report; this file does not substitute for the final gate.
- Android coverage is browser touch/mobile emulation. It does not claim execution on a physical Android handset.

## Independent source hardening follow-up

- Reproduced a distinct-identity collision: `WEBHOOK_EVENT / camera:west / track1` and `WEBHOOK_EVENT / camera / west:track1` normalized from two records to one. Replaced delimiter concatenation with JSON-encoded identity tuples in both normalization and selection, with a regression test.
- Reproduced valid 256-character target ID expanding a 360px mobile document to 1714px. Bounded the overview/action ID presentation and enabled attention-copy wrapping while preserving the complete ID in target detail. The same browser probe after the fix reports viewport=360, document=360 and detail ID length=256.
- The hostile optional-field probe included an object-valued uncertainty, object-valued alternative interpretation, object evidence and an HTML-looking evidence string. It produced no page errors and zero unexpected image nodes; objects use safe fallback and evidence remains text.
- Scenario unit suite now has 14 passing tests (24 together with the 10 unchanged historical helper tests).

## Source disambiguation and announcement follow-up

- Duplicate target IDs from different sources now show the source in the row and include source/source-kind in the accessible button name. Unique target labels are unchanged. Browser checks select the intended source independently and verify its detail provenance.
- A MutationObserver reproduced one redundant rewrite of the unchanged `role=status` error message per retry. The shared text-update guard now leaves identical announcements untouched; the executable retry test observes zero mutations.
- Strict `truncated: true` on a healthy canonical response now displays an independent limited-window notice. It does not become a connection failure and clears after an untruncated response.
- QA's screenshot showed Resume and Reset wrapping inside words at 393px. The transport group now retains its intrinsic width, uses compact padding and keeps button words on one line. A 393px touch probe verifies document width=393 and each label is a single 15px text line at 11px font size.
- Eight targeted browser checks passed across 360px touch emulation and desktop for source identity, independent selection, unchanged announcements and healthy truncated responses. These committed tests join the manager's full browser matrix.
