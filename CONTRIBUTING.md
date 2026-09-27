# Contributing

Use a feature branch and open a pull request. Do not commit user config, recordings, credentials,
model weights, or conversation history. Run the checks in README and TESTING. New protocol behavior
needs a fake-server regression test and an explicitly scoped live check before a compatibility claim.

Tests must never connect to a real account, microphone, or external challenge/service by default.
Use dependency injection, monotonic fake clocks, temporary directories, and bounded waits. A failure
to acknowledge an action is not permission to retry it. Human approval must not be bypassed for tests.

Keep UI work on the GTK thread, RPC waits on workers, and native model work in managed child processes.
Document configuration migrations and default changes. Prefer small follow-up PRs after this initial
hardening proposal is reviewed; do not add more autonomous capabilities without permission design.
