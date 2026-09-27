# Coverage of the requested improvements

Base reviewed: ridjan-xhika/JKI `9214e8df7db8ac7d1fbee8cccdafa129b4705fa9`.
This is a substantial development proposal, not a production certification.

| Review item | Implementation | Remaining validation/work |
| --- | --- | --- |
| Explicit permissions | Three profiles, safe legacy migration, explicit resume/new-turn policies, visible defaults | Native enforcement and concurrent-client behavior |
| Approval handling | Detailed on-screen command/file requests; no spoken approval; stale/unsupported requests rejected | Native decision routing; other request types not implemented |
| Real cancellation | Separate mute/speech/task controls; turn IDs, steering, interrupt; pre-send admission guard | Native server cancel/reconnect races |
| Dependable state | Independent component health, sticky approval/cancellation, uncertain outcomes, bounded queues | Long-duration desktop soak testing |
| Configuration/privacy | Custom-path persistence, schema/type checks, private atomic writes, transcript opt-in | OS crash/backup/temp-file policies remain external |
| Setup/install | Python package, console/desktop entry, terminal assistant, device/catalog discovery, explicit verified model installer | Curated downloadable manifests; graphical first-run wizard not implemented |
| Desktop portability | Optional layer-shell, terminal fallback, generic user service | GNOME/KDE/Hyprland test matrix; no macOS/Windows support |
| Performance | Lazy persistent workers, configurable resources, adaptive drawing, bounded metrics and benchmarks | Hardware ASR/GUI/battery baseline |
| Daily use | PTT, device selector/meter, editable transcript, reduced motion, spoken startup/progress/outcomes | Language-quality tests; desktop-global hotkeys not implemented |
| Quality/release | Unit/fake-transport tests, CI, core type-check job, package smoke, lock-generation helper | Remote CI/native tests and complete resolved runtime lock |
| Presentation | README, privacy/security/protocol docs, architecture, fixture demo, renderer assets | Authentic native screenshots/video and maintainer-designated security contact |

## Spoken progress behavior

After backend acceptance: “I'm doing it now.” While active: factual plan steps, assistant commentary,
and command/tool activity. Speech updates are coalesced and rate-limited; visible progress is not
held back by that rate limit. Approval, failure, completion, and interruption get distinct messages.
Stale progress is discarded after completion or while awaiting approval/cancellation. Normal progress
can be disabled independently; outcome/approval messages are not falsely converted into progress.

## Merge recommendation

Review the permission/protocol change first. Run the native checklist before marking this ready for
release. Keep the proposal as a draft while integration checks remain. Do not call an unexecuted CI
workflow a passing check or claim that the backend has performed a task based only on a fake fixture.

## Upstream compatibility and website

The latest upstream model persistence and model-specific reasoning controls are carried into the
modular engine. Saved model choices remain authoritative after reconnects. New tasks carry the
selected model and supported effort; settings changes during a task affect only the next new task.
Combined model/effort commands are validated before persistence.

The Jake AI static site adds an interactive WebGL orb, a fallback illustration, responsive landing
page, searchable documentation generated from these Markdown sources, and automatic Pages builds.
See [Website](WEBSITE.md) for the one-time Pages configuration and deployment rules.
