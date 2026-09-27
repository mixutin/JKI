# Changelog

## 0.2.0 — unreleased proposal

Explicit permission profiles and schema migration; human approval panel; separate task and speech
cancellation; bounded concurrent transport and stale-work rejection; independent health; accurate
spoken task acknowledgment and progress; PTT/transcript review/device selection; offline-only model
runtime and verified manifest installer; packaging/setup/diagnostics; adaptive orb rendering; tests,
CI and release documentation. Native integrations and a full dependency/model lock remain unverified.

### Upstream integration and Jake AI site

- Preserve upstream 9214e8d model selection persistence and catalog-specific reasoning controls.
- Apply selection changes to the next task without changing in-progress work.
- Add regression coverage for reconnects, config migration, and combined settings commands.
- Add a responsive Jake AI website with a procedural 3D orb and searchable source-derived docs.
- Add GitHub Pages build, link validation, preview artifacts, and deployment from main.
