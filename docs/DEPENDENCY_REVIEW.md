# Dependency review — 4 October 2026

Backlog item 3 reviews the six direct dependencies on Python 3.11.5. This is
a compatibility review with a fresh installation, not a claim that every pin
is the newest release or that a vulnerability scan passed.

## Direct pins and official evidence

Official documentation accessed on 2026-10-04. Newer releases below are those
visible in the reviewed notes, not a promise about future releases.

| Dependency | Before | Selected | Decision and evidence |
| --- | --- | --- | --- |
| FastAPI | 0.141.1 | 0.141.1 | Retained. [Official notes](https://fastapi.tiangolo.com/release-notes/#01422) list 0.142.0–0.142.2 adding OpenTelemetry and fixing startup/endpoint wrapping around that release. This prototype does not need that feature; avoid coupling the targeted Starlette fix to new automatic telemetry configuration. Installed 0.141.1 metadata permits `starlette>=0.46.0` and `pydantic>=2.9.0`. |
| Uvicorn | 0.52.4 | 0.52.4 | Retained. [Official notes](https://uvicorn.dev/release-notes/) list 0.53.0/0.54.0 with experimental HTTP/2, trailers and early hints, plus connection-handling fixes. The current local prototype does not enable that experimental transport. These newer changes are not required to resolve the observed test-stack warning; no socket-level server compatibility is claimed. |
| pytest | 9.1.1 | 9.1.1 | Retained. [Official changelog](https://docs.pytest.org/en/stable/changelog.html#pytest-9-1-1-2026-06-19) lists 9.1.1 as its latest release, fixing parametrized fixture and initial conftest regressions. Preserve the existing test runner and assertions. |
| Pydantic | 2.13.5 | 2.13.5 | Retained. [Official tagged release](https://github.com/pydantic/pydantic/releases/tag/v2.13.5) records validator reuse, garbage-collection traversal and smart-union fixes. The rendered documentation changelog stopped at 2.13.4; use the tagged release as evidence for this patch. |
| Starlette | 1.6.0 | **1.7.0** | Updated. [Official notes](https://starlette.dev/release-notes/#170-september-23-2026) explicitly fix deprecated AnyIO imports in TestClient for AnyIO 4.15, addressing the baseline warning. The release requires AnyIO 4 and also changes middleware/HTTP edge cases, so full application regressions are required. No experimental telemetry middleware is enabled by DroneWatch. |
| HTTPX2 | 2.12.0 | 2.12.0 | Retained. [Maintainer changelog](https://github.com/pydantic/httpx2/blob/main/src/httpx2/CHANGELOG.md) lists 2.13.0/2.13.1 changes to optional Brotli support, CLI TLS flags, abandoned streams, partially read file lengths and WebSocket keepalive. Current use is the in-process ASGI test client; those newer features/fixes are not needed for the demonstrated warning. This does not verify a future outbound Viso client. |

Only Starlette changes in `requirements.txt`. Exact direct pins do **not** lock
transitive dependencies across dates/platforms. Record the actual resolved
inventory alongside this review instead of claiming a cross-platform lockfile.

## Isolation and commands

The original `.venv` is preserved. The new environment is
`.pytest_cache/item3-dependencies/.venv`, already excluded by `.gitignore`.
It has no system site packages. Only pip 26.2.1 was copied as a bootstrap tool;
all application/test distributions were resolved and installed from public PyPI.

The run forbids deletion, including normal installer scratch cleanup. The
retained local helper `install-retained.py` disables pip's temporary-directory
cleanup, enforces repository-only writes/no removal, disables personal pip
configuration, netrc use and keyring, and invokes pip with:

```text
--isolated --no-cache-dir --disable-pip-version-check install
--keyring-provider disabled --no-input --only-binary=:all: --no-compile
--no-clean --index-url https://pypi.org/simple
--report .pytest_cache/item3-dependencies/install-report.json -r requirements.txt
```

The helper changes scratch retention only; it does not replace package resolution,
wheel contents, application code or test assertions. Wheel-only installation
avoids source-build tools and build cleanup. Installer output and a pip JSON
report remain ignored under `.pytest_cache/item3-dependencies/` for local review.

Validation uses the new environment's Python:

```sh
.pytest_cache/item3-dependencies/.venv/bin/python -B -m pip --no-cache-dir check
.pytest_cache/item3-dependencies/.venv/bin/python -B .pytest_cache/item3-dependencies-runner.py
node --test tests/*.test.cjs
.pytest_cache/item3-dependencies/.venv/bin/python -m compileall -q main.py demo_feed.py dronewatch tests
git diff --check
```

The retained pytest runner executes full discovery with sys capture, a fresh
repository-local base temp directory, all temp artifacts retained and a
filesystem guard. `test_observations_can_be_loaded_without_touching_ground_truth`
attempts to delete its generated ground-truth file; that known policy failure
must be counted and reported, not skipped or disguised as a passing suite.

The new `test_testclient_import_lifespan_and_request_without_deprecations` starts
a fresh interpreter, treats deprecations as errors and checks TestClient import,
ASGI lifespan startup/shutdown and a JSON request entirely in memory. A fresh
interpreter prevents earlier imports from hiding the original warning.

## Security and scope

`pip check` verifies installed dependency constraints; it is not a vulnerability
scan. **No vulnerability scan was run**: network access in this task is limited
to installation and documentation. CI retains its pinned `pip-audit==2.10.1`
installation and `python -m pip_audit -r requirements.txt` gate. Hosted CI was
not triggered. Local Node and macOS checks do not establish Linux/Node 24 CI
success. Nothing here validates Viso connectivity or real-world detection.

## Measured results

Fresh installation succeeded on macOS arm64 / Python 3.11.5 with pip 26.2.1.
All six installed direct versions exactly match the selected pins above. All
installed distributions resolve inside the new environment. The sanitized
[resolved inventory](results/dependency_review_20261004.json) records every
installed dependency version, wheel SHA-256, requirements hash and results.
Transitive `idna` resolved to 3.20, compared with 3.19 in the original environment;
the original environment also contains setuptools, which this wheel-only
installation does not need. This inventory is evidence, not a portable lockfile.

- Full Python suite: **290 passed, 1 failed, 0 skipped/errors**, 291 total,
  113.27 seconds. The sole failure is the unchanged ground-truth deletion
  test described above. No additional failures or dependency warnings appeared.
- The new strict TestClient regression passed with Starlette 1.7.0. As a negative
  control, that test alone failed in the original Starlette 1.6.0 environment on
  the deprecated `anyio.abc.BlockingPortal` import, proving it detects the issue.
- All **60 JavaScript tests passed**, zero skipped, with Node 26.8.1.
- `pip --no-cache-dir check`, compilation and `git diff --check` passed.
- The isolated environment is ignored by Git. Hashes of 3,252 original `.venv`
  files stayed unchanged across installation/verification. `index.html` matches
  HEAD byte-for-byte (SHA-256
  `e1d9be772509789c925ebe30b62a41e1642d5d8f250afa5d1edf484571a0b293`).

Full Python evidence:
`.pytest_cache/item3-dependencies-20261004T112126525652Z/python-results.xml`.
Negative-control evidence:
`.pytest_cache/item3-dependencies-20261004T112143344783Z/python-results.xml`.
JavaScript output: `.pytest_cache/item3-dependencies/javascript-results.txt`.
These local reports and installer scratch are retained for review; nothing was
removed. An unrestricted green Python run and a vulnerability audit remain
unverified. The original `.venv` still has the old dependency pin; use the isolated
environment for this review until the owner updates their normal environment.
