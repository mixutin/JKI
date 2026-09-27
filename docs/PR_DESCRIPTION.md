## Summary

Carry the supplied Jake Voice improvements onto current upstream `9214e8d` and add the Jake AI website.

- Modular engine, explicit permission profiles, transcript review, approval UI, bounded queues, and task lifecycle/progress controls.
- Preserve upstream model persistence and model-specific reasoning controls in the modular engine and GTK menu.
- Persist model/effort choices, keep them authoritative across reconnects, and apply them to the next new task without restarting ongoing work.
- Add a polished responsive Jake AI site with a procedural 3D WebGL orb, interactive design preview, and searchable documentation generated directly from repository Markdown.
- Add GitHub Pages builds for branches and PRs, automatic deployment from main, link/asset validation, metadata, sitemap, and a custom 404 page.

## Validation

- 113 Python tests passed; one opt-in live test skipped.
- One local Unix-WebSocket fixture was excluded because this environment prohibits Unix sockets; CI retains the test.
- Ruff and the existing four-module mypy gate passed.
- Website builds passed for both project-path and root-domain hosting; 18 pages and internal links/assets verified.
- Chromium browser checks passed at 390/768/1440 pixels: no horizontal overflow or page errors; orb states, preview, search, documentation, reduced motion, and WebGL fallback exercised.
- Wheel/sdist builds and isolated wheel CLI/engine smoke checks passed.
- See `docs/reports/upstream-site-validation.md` for details and limitations.

## Deployment and remaining validation

A repository administrator needs to select **Settings → Pages → Source → GitHub Actions** once. Production deployment is restricted to main; pull requests only build and upload the site artifact.

Native GTK/PipeWire/Vosk/Whisper/Piper and real Codex start/approval/steer/cancel/reconnect still require validation. This remains a 0.2.0 development proposal. No microphone or real Codex task was used during this revision's checks.
