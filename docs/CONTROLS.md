# A conversation you control

## Speak, review, send

Push-to-talk and editable transcript review are the defaults. Hold the talk button or use Ctrl+Space
while the Jake window has focus. Release to finish. Read the transcript, edit it if necessary, and
select Send. Focus loss ends capture. Wake-word listening is an optional input mode.

The wake word is not speaker authentication. Anyone within reach of the microphone may be heard.

## Models and reasoning

Choose a model in the desktop menu. Its available reasoning levels come from the connected account's
model catalog, including models whose options differ from one another. The reasoning menu is disabled
when the model exposes no levels.

You can also speak or type explicit settings commands:

- “Switch to Astra.”
- “Set reasoning to max.”
- “Use Sol with high reasoning.”
- “Change thinking to extra high.”

Jake saves model and effort choices to the configuration file you loaded, including a custom `--config`
path. Each new request carries the selected model and supported effort explicitly. A reconnect cannot
replace your saved model choice with the resumed thread's previous model.

Changes take effect on the **next new task**. They do not restart or change the model of a task already
running. An update sent during a task uses the task's steering operation and existing model. If a
new model does not support the previous effort, Jake selects a supported default. Invalid combined
model/effort requests leave the existing settings intact.

## Three independent controls

| Control | What it does |
| --- | --- |
| Mute microphone | Stops capture and invalidates queued voice input. |
| Stop speaking / Escape | Stops local speech playback without cancelling the task. |
| Cancel task / Ctrl+Escape | Requests backend cancellation and waits for confirmation. |

Cancellation does not undo changes already made. A connection failure or uncertain submission is not
a reason for Jake to replay your request. Check the conversation, then use the refresh/review controls.

## Approvals and progress

Review command and file approval details on screen before deciding. Missing or unsupported details
prevent acceptance. Jake reports observed plan steps, tool activity, and completed outcomes. Spoken
progress is throttled, and can be disabled. It does not invent percentages or announce success before
a terminal backend event.

## Keyboard scope

The shortcuts above work while the Jake window has focus. They are not global desktop shortcuts.
Reduced motion is available in the desktop UI. The website separately respects the system reduced-motion
preference and has an animation pause button.
