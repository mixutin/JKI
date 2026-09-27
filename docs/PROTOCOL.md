# Backend contract and limitations

Source-level contract checked against OpenAI Codex protocol schemas at commit
`67a709665ac7b50311b93e32612c9a8281684787`, including `AskForApproval.ts` and
`ThreadResumeResponse.ts` under `codex-rs/app-server-protocol/schema/typescript/v2/`.
This records schema evidence, not a successfully tested installed Codex release.

Primary references:
- https://developers.openai.com/codex/app-server
- https://github.com/openai/codex/blob/67a709665ac7b50311b93e32612c9a8281684787/codex-rs/app-server-protocol/schema/typescript/v2/AskForApproval.ts
- https://github.com/openai/codex/blob/67a709665ac7b50311b93e32612c9a8281684787/codex-rs/app-server-protocol/schema/typescript/v2/ThreadResumeResponse.ts

Transport remains the original project's local Unix-domain WebSocket. JKI sends initialize and
initialized before catalog/resume operations. The configured socket path is specific to the
installed Codex app; discovery is not claimed for arbitrary versions. Unsupported response shapes
block commands instead of inheriting permissions or guessing.

Implemented operations: model/list, thread/list during setup, thread/read, thread/resume, turn/start,
turn/steer with expectedTurnId, and turn/interrupt. No automatic retries of task submission.
Implemented notifications: turn start/completion, plan updates, item start/completion, errors,
serverRequest/resolved, and disconnect. Unknown notifications are ignored.
Implemented requests: commandExecution and fileChange approval, with on-screen accept/decline/cancel
when offered. Other requests (including permission grants, elicitation, and user-input forms) are
not implemented: they fail closed and require conversation review rather than a fabricated response.

Only terminal completed/failed/interrupted events announce an outcome. Intermediate assistant
messages, real plan steps, and tool lifecycle events feed progress. Startup acknowledgment follows
acceptance; fast completion can replace it rather than announce stale ongoing work.

## Pre-merge integration check

Use a disposable workspace/thread with restricted permissions. Record `codex --version`. Verify
read-only resume, workspace policy overrides, approval decision responses and resolution, steering,
cancellation before/after start acknowledgment, reconnect during an active turn, and failed turn
reporting. The unit protocol fixture proves the client logic against a fake server, not the native
application's private socket compatibility. Publish a supported-version matrix only after this test.
