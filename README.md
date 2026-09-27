# JKI (Jake Voice)

A small Linux desktop companion that listens for the wake word **Jake**, sends addressed requests to an existing Codex conversation, and speaks the replies. It includes an animated GTK orb, local wake-word and command recognition, local speech synthesis, model switching, and optional media controls.

## What it does

- Vosk listens locally for the wake word. Whisper transcribes a command only after Jake is addressed.
- Commands go to a Codex App Server thread over its local Unix socket.
- Piper provides neural speech synthesis. eSpeak NG is used if Piper is unavailable.
- The GTK orb shows listening, working, speaking, offline, and muted states.
- Optional `mpv`, `yt-dlp`, and `playerctl` integration handles music playback and controls.

Audio is processed locally and is not saved by JKI. Only commands addressed to Jake are sent to Codex. The wake word is not speaker authentication: anyone who can reach the microphone may be able to issue commands.

## Requirements

This version targets Linux, GTK 4, PipeWire, and a running Codex App Server. On Arch Linux, install the system packages that provide GTK 4, Gtk4LayerShell, PyGObject, Pycairo, PipeWire (`pw-record` and `pw-play`), and eSpeak NG. For music commands, install `mpv`, `yt-dlp`, and `playerctl`.

Create the application directory and a virtual environment that can see the system GTK bindings:

```sh
mkdir -p ~/.local/share/jake-voice
python -m venv --system-site-packages ~/.local/share/jake-voice/venv
~/.local/share/jake-voice/venv/bin/pip install -r requirements.txt
```

Copy `engine.py`, `jake.py`, `music.py`, and `orb.py` into `~/.local/share/jake-voice/`. Download the Vosk model from [alphacephei.com/vosk/models](https://alphacephei.com/vosk/models) and extract it under `~/.local/share/jake-voice/`. Whisper's `base.en` model is downloaded by faster-whisper on first use. Download the Piper voice with:

```sh
~/.local/share/jake-voice/venv/bin/python -m piper.download_voices en_US-lessac-medium --download-dir ~/.local/share/jake-voice/voices
```

Create the configuration directory and copy `config.example.json` to `~/.config/jake-voice/config.json`. Set `thread_id` to the Codex conversation to attach to, and update the model, Codex socket, and Codex CLI paths for your machine. Use absolute paths. Set `full_access` to `true` only if you want Codex to use the current user's full filesystem and application permissions; it does not grant root access. The wake word does not verify who is speaking.

## Start at login on Hyprland

Copy `jake-voice.service` to `~/.config/systemd/user/jake-voice.service`, then enable it:

```sh
systemctl --user daemon-reload
systemctl --user enable --now jake-voice.service
```

The unit is attached to `hyprland-session.target`. Ensure your compositor imports its Wayland environment into the systemd user manager before starting that target. Ryoku does this during Hyprland startup. On another desktop, adapt the target and environment import to that session.

Useful commands:

```sh
systemctl --user status jake-voice.service
systemctl --user stop jake-voice.service
journalctl --user -u jake-voice.service -f
~/.local/share/jake-voice/venv/bin/python ~/.local/share/jake-voice/jake.py check
```

Run the unit tests from this repository with `python -m unittest`.

## Configuration example

See [`config.example.json`](config.example.json). It contains placeholders only; do not publish your personal configuration file or model files.

## License

JKI source code is provided under the MIT License. Speech models and runtime dependencies have their own licenses; obtain and use them according to their respective terms.
