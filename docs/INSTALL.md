# Installation and first-run checks

## System dependencies

Target: Linux, Python 3.11+, GTK 4, PyGObject, Pycairo, PipeWire, and a compatible local Codex App
Server. The GTK layer-shell extension is optional; without it JKI uses an ordinary GTK window.

Ubuntu/Debian starting recipe (package availability depends on the distribution release):

```sh
sudo apt install python3-venv python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-4.0 pipewire-bin espeak-ng
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
python -m pip install '.[audio]'
jki setup
jki doctor
```

Other distributions: install packages providing the same components, plus optional Gtk4LayerShell
for supported Wayland compositors. Do not replace distribution-managed GTK packages with an
unreviewed root-level pip installation. Optional media needs `mpv`, `yt-dlp`, `playerctl`, and `wpctl`.

The setup assistant preserves custom config paths, explains privacy, discovers local conversations
and models only on request, lists devices, and asks for explicit full-access confirmation. It does
not turn on autostart or start recording. Have the Vosk/Whisper/Piper files ready first; see MODELS.
The JSON example uses placeholder absolute paths and is not ready to run unchanged.

## Desktop startup

```sh
jki install-desktop
systemctl --user daemon-reload
# Only after foreground audio and permissions tests succeed:
systemctl --user enable --now jake-voice.service
```

The generated launcher/service uses the current Python environment and selected config path.
Keep that environment in a stable location. The service is attached to `graphical-session.target`;
your desktop must actually start that target and supply `DISPLAY` or `WAYLAND_DISPLAY` and the
session D-Bus environment. A service that starts before the graphical session is not a supported
substitute. Paths with newline, NUL, dollar, or backtick characters are rejected by the launcher
writer to avoid different expansion behavior between desktop and systemd parsers.

For a compositor with a dedicated session target, use a user-unit override appropriate to that
session. In Hyprland, import the compositor's actual session environment and associate the unit
with `hyprland-session.target` if that target is supplied by your session configuration. Do not
blindly start a target that your desktop does not own. The sample service is not auto-enabled.

```sh
systemctl --user status jake-voice.service
journalctl --user -u jake-voice.service
systemctl --user disable --now jake-voice.service
```

## Desktop validation matrix

| Environment | Implementation | Validation status for this proposal |
| --- | --- | --- |
| Linux headless core | Supported for unit tests/CLI | Tested locally |
| GTK 4 normal window | Fallback implemented | Native test pending; CI smoke provided |
| Hyprland/Wayland layer shell | Optional overlay implemented | Native test pending |
| GNOME/KDE/X11 sessions | Normal-window/startup recipes | Native test pending; not certified |
| macOS/Windows | No capture/service/UI adapters | Not supported |

## Daily controls

Hold the button or Ctrl+Space to talk. Escape stops speech; Ctrl+Escape requests task cancellation.
These shortcuts are **window-scoped**, not desktop-global compositor shortcuts. Focus loss ends
push-to-talk. Muting invalidates captured/queued voice work but does not undo work already sent.
There is no wake-word interruption while speech is playing; use the button or keyboard controls.

A missing terminal does not crash the engine: configure an executable in setup or install one of
the supported terminal emulators. The Open conversation action deliberately opens a separate
Codex CLI client; its permissions are governed by that client. Close or adjust it independently.
