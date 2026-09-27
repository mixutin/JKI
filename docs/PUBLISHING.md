# Publishing and maintaining this proposal

The proposal is based on upstream `9214e8df7db8ac7d1fbee8cccdafa129b4705fa9` and is intended for an
upstream pull request from the writable `mixutin/JKI` fork. Its modular engine includes the upstream
model persistence and reasoning controls. The website and Pages workflow are included in the same change.

## Review and validation

See [the current validation report](reports/upstream-site-validation.md), [implementation status](IMPLEMENTATION.md),
and [website deployment](WEBSITE.md). Native audio/GTK and live Codex task validation remain necessary
before calling the application production-ready. A source commit or a website build is not evidence
that those integrations were exercised.

## Optional local publishing helper

`tools/publish_pr.py` remains available as an alternative for an authenticated GitHub CLI environment.
Its default invocation only verifies `SOURCE-MANIFEST.json`. The explicit `--publish` path creates a
new branch and draft PR, checks the expected account and upstream base, and never force-pushes or merges.
Prefer updating the existing PR after publication instead of creating a duplicate.

```sh
python tools/publish_pr.py
```

The manifest is a source-integrity check, not a publisher signature. Regenerate it after intentional
source changes before using the helper. Its live GitHub CLI path is separate from connected-tool
publication and has not been used for this revision.
