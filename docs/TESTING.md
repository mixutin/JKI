# Testing and release validation

The current validation report is in `reports/upstream-site-validation.md`. The upstream integration
passes 113 tests, with one opt-in live test skipped and the local Unix-WebSocket fixture excluded
because this execution environment forbids opening Unix sockets. CI retains that fixture and runs it
normally. Ruff and the four-module mypy gate pass. Native GTK/PipeWire and live Codex tasks still need
validation; they are not covered by the website's browser tests.

The website was built for both a GitHub project path and a root domain. A real headless Chromium run
checked 390, 768, and 1440-pixel widths, WebGL rendering/state controls, the interactive preview, search,
docs, reduced motion, and the static fallback. No page errors or horizontal overflow were observed.

Earlier bundle reports are historical evidence from the original source package. The current report
separates those results from this upstream integration run.

```sh
python -m unittest discover -v
python -m pytest -q
ruff check .
mypy jki/config.py jki/state.py jki/text.py jki/speech_queue.py
python -m build
python tools/wheel_smoke.py dist
xvfb-run -a python tools/gui_smoke.py
```

Type checking currently targets the typed configuration/state/text/queue modules, not every GTK
callback or native-library binding. CI uses read-only repository permission and no account secrets.
The optional read-only integration check is explicit:

```sh
JKI_LIVE_TESTS=1 JKI_TEST_CONFIG=/absolute/test-config.json python -m unittest tests.test_live -v
```

This only handshakes, reads the thread, and lists models. A maintainer still must exercise actual
mutating operations in a disposable workspace; the integration test does not grant permission to
perform them automatically.

## Required native checklist before release

Check startup with missing microphone, model, terminal and backend. Validate restricted/workspace/full
profiles and escalation approval; deny missing-context requests. Mute during transcription, cancel
before and after submission acknowledgment, cancel during synthesis/playback, unplug/replug a selected
mic, lose keyboard focus during PTT, and restart the backend during an active task. Confirm uncertainty
is visible and no actions replay. Test completed/failed/interrupted outcomes and delayed duplicate events.

Use English and any additional advertised language with actual matching models. Measure false wake
activations in realistic noise. Test several hours of idle/active use and observe subprocess, descriptor,
and memory counts. Measure GUI CPU and battery usage rather than infer savings from timer rates.
Verify actual desktop startup/environment propagation before adding a row to the tested-desktop matrix.

## Dependency locking

`pyproject.toml` expresses compatibility ranges; `requirements.txt` is not a lock. The actual installed
core-tool versions are recorded separately, not misrepresented as a full audio runtime lock. Generate
hashed per-Python locks on a network-enabled Linux build host, install them, and run native tests:

```sh
python tools/lock_dependencies.py --python 3.12
python -m pip install --require-hashes -r packaging/requirements-python3.12.lock
python -m pip install --no-deps .
```

Record OS/architecture and model revisions alongside each validated lock. Review updater PRs; do not
silently regenerate hashes at user startup. Speech-model licenses need separate review.
