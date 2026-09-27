"""Console entry point; help, setup, and diagnostics do not import GTK."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from . import __version__
from .config import CONFIG, DATA, ConfigError, ConfigStore, Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JKI / Jake Voice: local speech companion for Codex")
    parser.add_argument("command", nargs="?", default="run", choices=[
        "run", "setup", "doctor", "check", "devices", "models", "say", "benchmark", "install-desktop", "demo"])
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--json", action="store_true", help="Print machine-readable diagnostics")
    parser.add_argument("--live", action="store_true", help="Opt into read-only local Codex checks")
    parser.add_argument("--text", default="Speech playback is working.")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--destination", type=Path, default=DATA / "models")
    parser.add_argument("--wav", type=Path, help="Optional local WAV for real offline ASR benchmarking")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args(argv)
    store = ConfigStore(args.config)
    try:
        if args.command == "setup":
            from .setup import setup
            setup(store)
            return 0
        if args.command == "devices":
            from .diagnostics import devices
            print(json.dumps(devices(), indent=2))
            return 0
        if args.command == "models":
            from .models import install_manifest
            if not args.manifest:
                raise ConfigError("Use jki models --manifest /path/to/trusted-manifest.json")
            result = install_manifest(args.manifest, args.destination,
                                      progress=lambda name, done, total: print(f"{name}: {done}/{total} bytes", file=sys.stderr))
            print(result)
            return 0
        if args.command == "demo":
            from .demo import DemoEngine
            from .ui import run_gui
            with tempfile.TemporaryDirectory() as directory:
                engine = DemoEngine(Settings(thread_id="demo"), Path(directory) / "config.json")
                return run_gui(engine, demo=True)
        settings = store.load()
        if args.command in {"doctor", "check"}:
            from .diagnostics import doctor
            report = doctor(settings, live=args.live)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                for check in report["checks"]:
                    print(f"{check['status'].upper():7} {check['name']}: {check['detail']}")
            return 0 if report["ok"] else 1
        if args.command == "install-desktop":
            from .desktop import install_desktop
            paths = install_desktop(store.path)
            print("Created:\n" + "\n".join(map(str, paths)))
            print("Autostart is NOT enabled. See docs/INSTALL.md before enabling the user service.")
            return 0
        if args.command == "benchmark":
            from .benchmark import benchmark
            print(json.dumps(benchmark(settings, wav_path=args.wav, iterations=args.iterations), indent=2))
            return 0
        from .engine import Engine
        engine = Engine(settings, store.path)
        if args.command == "say":
            from .audio import AudioPipeline
            engine.audio = AudioPipeline(engine)
            engine.say(args.text)
            engine._spawn(engine.audio.speech_loop, "speech-test")
            try:
                deadline = time.monotonic() + 150
                while time.monotonic() < deadline:
                    snapshot = engine.snapshot()
                    if snapshot["tts_health"] == "error":
                        raise RuntimeError("Speech output test failed. Run jki doctor.")
                    if "playback_duration" in snapshot["metrics"]:
                        return 0
                    time.sleep(.1)
                raise TimeoutError("Speech output test timed out")
            finally:
                engine.close()
        settings.validate_runtime()
        from .ui import run_gui
        return run_gui(engine)
    except (ConfigError, ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"JKI: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
