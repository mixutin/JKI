# Data handling

Microphone samples are held in bounded memory buffers. Vosk sees wake-mode input locally. Whisper
receives only accepted utterances, or explicit push-to-talk captures. Transcription child processes
are offline-only. JKI does not deliberately save microphone recordings. OS swap, crash dumps,
audio-server behavior, and backups are outside that guarantee.

Recognized text stays in memory for the editable preview. An accepted command and a short voice
formatting instruction go to the configured local Codex socket; Codex may forward data to its
model service under its own configuration. Conversation history remains governed by Codex.

Speech synthesis creates temporary output WAV files and, for eSpeak, temporary input text. Files
are removed after playback/cancellation. Abrupt process or machine failure can leave temporary
files; use appropriate encrypted storage and OS temporary-file cleanup. “Local audio” does not
mean “no temporary speech files” or “no text leaves the computer.”

The status file contains only state, connection, selected model/profile, schema, and PID by default.
`persist_transcript=true` explicitly adds the latest recognized command. The normal shutdown path
removes the status file. Errors, progress, approvals, paths, and previews are not serialized there.
A crash can leave stale status; consumers should check its PID rather than trust it as a live signal.

The metrics buffer stores durations and counts only, not transcript text or tool parameters.
JKI does not log raw backend payloads or audio. Diagnostic output may include local configuration
hints; inspect it before sharing. Live doctor mode requires `--live` and only reads local backend
metadata. Model installation contacts the HTTPS URLs in the user-selected manifest. Optional media
search/playback contacts external services through mpv/yt-dlp and is outside the Codex sandbox.
