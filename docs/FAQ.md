# Questions & answers

## What are Jake AI, Jake Voice, and JKI?

Jake AI is the website identity. Jake Voice is the Linux desktop application, and JKI is the source
repository and Python package namespace. Jake is an independent community project, not an official
OpenAI product.

## Is everything offline?

Speech recognition and speech synthesis run locally when their models are installed. Commands you
choose to send go to Codex through its local App Server connection and may use remote services.
Optional media lookup also uses the network. Read the [privacy guide](PRIVACY.md).

## Does the website listen to me?

No. The 3D orb and interactive desktop preview are visual demonstrations. The site never requests
microphone access, starts an AI task, or connects to your Codex account. The site includes no analytics
or third-party font/script requests. GitHub Pages is the hosting provider.

## Which platforms are supported?

The implementation targets Linux with Python 3.11+, GTK 4, PipeWire, and a compatible local Codex App
Server. Optional layer-shell support is intended for compatible Wayland compositors. macOS and Windows
adapters are not implemented. See the actual [validation matrix](INSTALL.md#desktop-validation-matrix).

## Can I install a finished release?

This branch is a 0.2.0 development proposal. Install from source using the [installation guide](INSTALL.md).
Native audio/desktop and live Codex workflows still require validation. The site does not advertise
unverified binaries or promise a production-ready release.

## How do I change the model or reasoning level?

Use the desktop menus or an explicit request such as “Use Sol with high reasoning.” Available choices
come from your account's model catalog. Selections are saved and apply to the next new task.
See [daily controls](CONTROLS.md).

## How can I help?

Read [Contributing](../CONTRIBUTING.md), run the tests, and include reproducible details in issues.
Hardware testing and compatibility reports are especially useful. Keep account details, conversation
contents, recordings, and personal config out of public reports.
