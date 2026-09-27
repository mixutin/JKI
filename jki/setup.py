"""Interactive first-run setup; network and microphone checks are opt-in."""
from dataclasses import asdict
from pathlib import Path
import shutil
from typing import Callable

from .config import ConfigStore, DATA, Settings
from .diagnostics import devices
from .models import install_manifest
from .protocol import CodexClient


def setup(store: ConfigStore, *, ask: Callable[[str], str] = input, output: Callable[[str], None] = print) -> Settings:
    output("JKI / Jake Voice setup. Speech is local; accepted commands go to Codex.")
    output("A wake word is NOT speaker authentication. Start with push-to-talk and transcript review.")
    values = asdict(store.load()) if store.path.exists() else asdict(Settings(workspace=str(Path.cwd())))

    def field(key: str, label: str) -> None:
        value = ask(f"{label} [{values[key]}]: ").strip()
        if value:
            values[key] = value

    field("socket_path", "Codex Unix socket")
    field("workspace", "Workspace (absolute directory)")
    if ask("Read your local Codex conversation/model catalog now? [y/N]: ").lower() == "y":
        client = None
        try:
            client = CodexClient(values["socket_path"], lambda event: None)
            threads = client.call("thread/list", {"limit": 20}).get("data", [])
            for index, thread in enumerate(threads, 1):
                output(f"{index}: {thread.get('name') or thread.get('preview', '')[:70]} ({thread['id']})")
            choice = ask("Conversation number (blank to enter an ID): ").strip()
            if choice:
                values["thread_id"] = threads[int(choice) - 1]["id"]
            models = client.call("model/list", {"limit": 100}).get("data", [])
            available = [m["model"] for m in models if not m.get("hidden", False)]
            output("Available models: " + ", ".join(available))
            if not values["model"] and available:
                values["model"] = available[0]
        except Exception as exc:
            output(f"Catalog discovery unavailable ({type(exc).__name__}); enter the details below.")
        finally:
            if client:
                client.close()
    field("thread_id", "Conversation ID")
    field("model", "Model ID (blank uses the conversation default)")
    output("Restricted: read-only tools. Workspace: writes inside the workspace, network off by default.")
    output("Full: broad current-user filesystem and network access. None of these grant root privileges.")
    field("permission_profile", "Permission profile: restricted / workspace / full")
    values["full_access_acknowledged"] = False
    if values["permission_profile"] == "full":
        if ask("Type ENABLE FULL ACCESS to confirm: ") != "ENABLE FULL ACCESS":
            values["permission_profile"] = "restricted"
            output("Full access not enabled; using restricted mode.")
        else:
            values["full_access_acknowledged"] = True
    field("input_mode", "Input mode: push-to-talk / wake-word")
    field("wake_word", "Wake word")
    field("language", "Speech language: en / fi / another ISO code / auto")
    field("transcription_model_path", "Local Whisper directory or already-cached model name")
    if values["input_mode"] == "wake-word":
        field("model_path", "Local Vosk model directory for your language")
    try:
        for device in devices():
            output(f"{device['kind']}: {device['description']} — {device['name']}")
    except Exception:
        output("PipeWire device discovery unavailable; blank device names use system defaults.")
    field("microphone", "Microphone node.name")
    field("output_device", "Output node.name")
    field("tts_engine", "Speech output: espeak / piper")
    if values["tts_engine"] == "piper":
        field("tts_model_path", "Piper ONNX file (needs adjacent .onnx.json)")
    field("voice", "eSpeak voice matching your language")
    values["preview_transcript"] = ask("Review transcripts before sending? [Y/n]: ").lower() != "n"
    values["spoken_progress"] = ask("Speak ongoing task progress updates? [Y/n]: ").lower() != "n"
    values["persist_transcript"] = ask("Persist the last transcript on disk? [y/N]: ").lower() == "y"
    values["media_enabled"] = ask("Enable local media/volume controls outside the Codex sandbox? [y/N]: ").lower() == "y"
    values["codex_path"] = shutil.which("codex") or values["codex_path"]
    field("terminal", "Preferred terminal executable (blank selects an installed terminal)")
    manifest = ask("Trusted, hash-pinned model manifest to install (blank skips download): ").strip()
    if manifest:
        path = install_manifest(Path(manifest), DATA / "models",
                                progress=lambda name, done, total: output(f"{name}: {done}/{total} bytes"))
        output(f"Verified model installed under {path}; set its local paths using jki setup.")
    settings = Settings.from_dict(values)
    settings.validate_runtime()
    store.save(settings)
    output(f"Configuration saved to {store.path}. No microphone was opened and no task was started.")
    output("Run jki doctor, then jki run. Autostart is separate and opt-in.")
    return settings
