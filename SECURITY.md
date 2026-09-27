# Security boundaries

A microphone and wake word are not identity verification. Someone near the microphone, a speaker,
or a media source may cause a command to be recognized. Push-to-talk plus transcript review is the
default, not a claim that voice is authenticated. Never use spoken approval for a sensitive action.

## Permission profiles

`restricted` requests a read-only sandbox. It does not promise that all private files are unreadable.
`workspace` requests workspace-only writable roots, disabled network, and exclusion of default
writable temporary locations for each new turn. `full` requests broad current-user access and
requires explicit setup confirmation. No profile grants root by itself. The backend must enforce
the requested policy. Approval can authorize an operation outside the normal sandbox; inspect it.

Every resumed session explicitly requests `on-request` approval policy, sandbox mode, and workspace.
The engine verifies the returned sandbox type, approval policy, and workspace before admitting
commands. Each new turn also carries its explicit sandbox policy. The UI reports the confirmed
**resumed defaults**, not an attestation about an independently started turn in another client.
The app will not silently steer a turn it does not own. Do not alter permissions concurrently in
another client and assume that JKI's UI attests to those changes.

Command/file approval requests are bound to the current connection and turn. Missing or oversized
context disables acceptance. The UI offers only supported server-provided decisions. Unknown
interaction types are rejected rather than auto-approved. Approval details are plain text, not
executed markup. Review expanded details before accepting; no semantic safety classifier is claimed.

Optional local media controls run as the current user **outside** Codex's sandbox. They are a
separate explicit opt-in. Configured executables, models, and the local backend must be trusted.
Status/config files are written via private temporary files and atomic replacement. Keep their
parent directories user-owned and private; a compromised same-user process is outside this design.
The Unix socket should be user-owned under a directory not writable by others; doctor checks this.

## Reporting

Do not post credentials, transcripts, recordings, private paths, or working exploitation details
in a public issue. Contact the maintainer through an available private channel first. A dedicated
security contact/process still needs maintainer designation; none is invented here.
