# JKI upstream integration and Jake AI website

## Scope

This revision carries the attached improvement proposal onto upstream
`9214e8df7db8ac7d1fbee8cccdafa129b4705fa9` (persistent model selection and reasoning controls).

- Preserve the modular engine, approvals, start/steer/cancel lifecycle, bounded queues, audio adapters,
  configuration storage, packaging, setup, diagnostics, tests, and documentation from the supplied bundle.
- Preserve saved model selections across reconnects, retain model catalog reasoning metadata, provide
  model-specific effort controls, and apply choices explicitly to new tasks.
- Accept combined model/effort commands atomically and allow next-task selections while a task runs.
- Add the Jake AI website with a procedural WebGL orb, responsive layout, preview controls, searchable
  documentation generated from repository Markdown, metadata, sitemap, and a custom 404 page.
- Add a Pages workflow that builds branches and PRs and deploys only from main after Pages is enabled.

## Validation

See `docs/reports/upstream-site-validation.md` for this revision's actual results and limitations.
Website screenshots are browser captures of the website; they are not native desktop screenshots.

The original bundle's historical reports remain in `docs/reports`. Native GTK/audio and live Codex
workflows are still pending and must not be inferred from unit tests or website browser validation.
