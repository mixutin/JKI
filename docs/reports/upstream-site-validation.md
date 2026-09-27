# Upstream integration and website validation

Base: `ridjan-xhika/JKI@9214e8df7db8ac7d1fbee8cccdafa129b4705fa9`.

## Core and packaging

- `pytest`: **113 passed, 1 skipped, 1 deselected**, plus 17 passing subtests.
- The opt-in live Codex check was skipped. The real local Unix-WebSocket transport fixture was
  deselected after the full suite demonstrated `PermissionError: Operation not permitted` while
  creating a Unix socket in this execution environment. It remains enabled in CI.
- Ruff: all checks passed.
- Mypy: no issues in configuration, state, text, and speech queue modules.
- Wheel and sdist built successfully with `python -m build`.
- Wheel installed without dependency downloads into an isolated target; CLI help/version and engine
  construction passed from outside the checkout.
- New regressions cover saved model selection after a stale resume response, paginated catalogs,
  combined model/effort persistence, invalid combined settings, supported defaults, models without
  reasoning controls, future catalog identifiers, legacy config migration, and next-task settings.

Environment: Linux x86_64, Python 3.12; core tests use fake backends and owned subprocesses.
The existing bundle reports record a separate earlier run and are historical evidence.

## Website

- Built **18 pages** from source documentation, for both `/JKI/` project hosting and a root-domain URL.
- All internal links, fragment targets, and referenced assets passed the builder's validator.
- JavaScript syntax checks passed.
- Real Chromium browser checks at **390, 768, and 1440 pixels** found no horizontal overflow or page errors.
- Procedural WebGL rendering, orb state selection, interactive preview, documentation search, docs
  navigation, system reduced-motion behavior, and the no-WebGL fallback passed.
- Desktop, mobile, and documentation screenshots were visually inspected. The committed website
  screenshot is a browser capture of the website, not a screenshot of the native app.

## Deployment and remaining checks

The Pages workflow builds branches and PRs with read permissions. Production deployment is restricted
to main and uses a separate Pages environment and deployment permissions. An administrator must enable
GitHub Actions as the Pages publishing source once. Remote workflow results must be checked on GitHub.

Native GTK/PipeWire/Vosk/Whisper/Piper and real Codex task start/approval/steer/cancel/reconnect are still
unvalidated in this environment. No microphone, private conversation, or real Codex task was used.
