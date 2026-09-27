"""GTK 4 controls. All backend RPC work stays off the GTK event thread."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import threading
import time

from .config import STATE
from .desktop import StatusFile, open_conversation
from .diagnostics import devices


def refresh_interval(snapshot, mapped: bool, reduced_motion: bool) -> int:
    if not mapped:
        return 1000
    return 50 if not reduced_motion and snapshot["status"] in {"working", "hearing", "speaking"} else 250


def run_gui(engine, *, demo: bool = False) -> int:
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, Gdk, GLib
    from .orb import draw_orb
    layer_shell = None
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gtk4LayerShell
        layer_shell = Gtk4LayerShell
    except (ValueError, ImportError):
        pass  # Normal GTK windows work without the optional layer-shell extension.
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(STATE / "instance.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        print("JKI is already running.")
        return 0
    status_file = StatusFile()
    app = Gtk.Application(application_id="local.jake.Voice")
    running = {"value": True}
    started = time.monotonic()

    def activate(application):
        window = Gtk.ApplicationWindow(application=application)
        window.set_title("JKI · Jake Voice" + (" — DEMO, no microphone or backend" if demo else ""))
        window.set_default_size(420, 680)
        if layer_shell and layer_shell.is_supported():
            layer_shell.init_for_window(window)
            layer_shell.set_namespace(window, "jake-voice")
            layer_shell.set_layer(window, layer_shell.Layer.TOP)
            layer_shell.set_keyboard_mode(window, layer_shell.KeyboardMode.ON_DEMAND)
            for edge in (layer_shell.Edge.RIGHT, layer_shell.Edge.BOTTOM):
                layer_shell.set_anchor(window, edge, True)
                layer_shell.set_margin(window, edge, 24)
        scroller = Gtk.ScrolledWindow()
        window.set_child(scroller)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for side in ("top", "bottom", "start", "end"):
            getattr(box, "set_margin_" + side)(16)
        scroller.set_child(box)
        title = Gtk.Label(label="JKI · JAKE VOICE", xalign=0)
        title.add_css_class("title-2")
        box.append(title)
        policy = Gtk.Label(xalign=0)
        policy.set_wrap(True)
        box.append(policy)
        orb = Gtk.DrawingArea()
        orb.set_content_height(150)
        box.append(orb)
        last_snapshot = {"value": engine.snapshot()}
        reduce_motion = Gtk.CheckButton(label="Reduced motion")
        gtk_settings = Gtk.Settings.get_default()
        reduce_motion.set_active(engine.settings.reduced_motion or not gtk_settings.get_property("gtk-enable-animations"))

        def draw(_area, ctx, width, height):
            state = last_snapshot["value"]
            animated = state["status"] in {"working", "hearing", "speaking"} and not reduce_motion.get_active()
            elapsed = time.monotonic() - started if animated else 0
            draw_orb(ctx, width, height, state["status"], elapsed, state["level"] if animated else 0)
        orb.set_draw_func(draw)
        status = Gtk.Label(xalign=0)
        status.set_wrap(True)
        status.add_css_class("title-3")
        detail = Gtk.Label(xalign=0)
        detail.set_wrap(True)
        detail.set_selectable(True)
        box.append(status)
        box.append(detail)
        level = Gtk.LevelBar()
        level.set_tooltip_text("Live microphone input level")
        box.append(level)

        def guarded(function):
            try:
                function()
            except Exception as exc:
                with engine.lock:
                    engine.health.error = str(exc)[:1000]

        def button(label, callback, parent=box):
            control = Gtk.Button(label=label)
            control.connect("clicked", lambda *_: guarded(callback))
            parent.append(control)
            return control

        row = Gtk.Box(spacing=6)
        box.append(row)
        mute = button("Mute microphone", engine.toggle_mute, row)
        button("Stop speaking · Esc", engine.stop_speaking, row)
        cancel = button("Cancel task", engine.cancel_task)
        cancel.set_tooltip_text("Ctrl+Escape. Requests cancellation; it cannot undo earlier changes.")
        ptt = Gtk.Button(label="Hold to talk · Ctrl+Space")
        gesture = Gtk.GestureClick()
        gesture.connect("pressed", lambda *_: guarded(engine.begin_capture))
        gesture.connect("released", lambda *_: engine.end_capture())
        gesture.connect("stopped", lambda *_: engine.end_capture())
        ptt.add_controller(gesture)
        box.append(ptt)
        modes = Gtk.DropDown.new_from_strings(["Push-to-talk", "Wake word"])
        modes.set_selected(0 if engine.settings.input_mode == "push-to-talk" else 1)
        modes.connect("notify::selected", lambda widget, *_: guarded(
            lambda: engine.set_input_mode("push-to-talk" if widget.get_selected() == 0 else "wake-word")))
        box.append(modes)
        microphone = Gtk.DropDown.new_from_strings(["System default microphone"])
        microphone.set_tooltip_text("Select a PipeWire microphone")
        device_names = [""]
        box.append(microphone)

        def populate_devices(found):
            if not running["value"]:
                return False
            sources = [device for device in found if device["kind"] == "input"]
            device_names[:] = [""] + [device["name"] for device in sources]
            microphone.set_model(Gtk.StringList.new(["System default microphone"] + [device["description"] for device in sources]))
            if engine.settings.microphone in device_names:
                microphone.set_selected(device_names.index(engine.settings.microphone))
            microphone.connect("notify::selected", lambda widget, *_: guarded(
                lambda: engine.set_microphone(device_names[widget.get_selected()])))
            return False

        def discover():
            try:
                found = devices()
            except Exception:
                found = []
            GLib.idle_add(populate_devices, found)
        if not demo:
            threading.Thread(target=discover, daemon=True).start()

        transcript = Gtk.Entry()
        transcript.set_placeholder_text("Review speech here, or type a command")
        transcript.set_max_length(8000)
        box.append(transcript)
        token = {"value": ""}

        def submit():
            text = transcript.get_text()
            accepted = (engine.confirm_preview(text, token["value"]) if token["value"] else engine.submit(text))
            if accepted:
                transcript.set_text("")
                token["value"] = ""
        transcript.connect("activate", lambda *_: guarded(submit))
        send_row = Gtk.Box(spacing=6)
        box.append(send_row)
        button("Send", submit, send_row)
        button("Discard", lambda: (engine.discard_preview(), transcript.set_text(""), token.update(value="")), send_row)
        model_menu = Gtk.DropDown.new_from_strings(["Waiting for model catalog"])
        model_ids = []
        updating_model = {"value": False}

        def select_model(widget, *_):
            index = widget.get_selected()
            if not updating_model["value"] and index < len(model_ids):
                engine.select_model(model_ids[index])
        model_menu.connect("notify::selected", select_model)
        box.append(model_menu)
        effort_menu = Gtk.DropDown.new_from_strings(["Waiting for model catalog"])
        effort_ids = []
        updating_effort = {"value": False}

        def select_effort(widget, *_):
            index = widget.get_selected()
            if not updating_effort["value"] and index < len(effort_ids):
                engine.select_effort(effort_ids[index])
        effort_menu.connect("notify::selected", select_effort)
        box.append(effort_menu)
        approvals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(approvals)
        approval_key = {"value": None}
        button("Open conversation", lambda: open_conversation(engine.settings))
        button("Refresh task state", engine.resync)
        button("I've checked the conversation · dismiss error", engine.acknowledge_review)
        reduce_motion.connect("toggled", lambda widget: guarded(
            lambda: engine.set_reduced_motion(widget.get_active())))
        box.append(reduce_motion)
        diagnostics = Gtk.Label(xalign=0)
        diagnostics.set_wrap(True)
        box.append(diagnostics)

        keys = Gtk.EventControllerKey()
        def pressed(_controller, key, _code, modifiers):
            if key == Gdk.KEY_Escape:
                guarded(engine.cancel_task if modifiers & Gdk.ModifierType.CONTROL_MASK else engine.stop_speaking)
                return True
            if key == Gdk.KEY_space and modifiers & Gdk.ModifierType.CONTROL_MASK:
                guarded(engine.begin_capture)
                return True
            return False
        keys.connect("key-pressed", pressed)
        keys.connect("key-released", lambda _c, key, *_: engine.end_capture() if key == Gdk.KEY_space else None)
        window.add_controller(keys)
        window.connect("notify::is-active", lambda *_: None if window.is_active() else engine.end_capture())
        previous = {"draw": None}

        def refresh():
            if not running["value"]:
                return False
            snapshot = engine.snapshot()
            last_snapshot["value"] = snapshot
            status.set_text(snapshot["detail"])
            detail.set_text(snapshot["progress"] or ("Last task: " + snapshot["last_result"] if snapshot["last_result"] else ""))
            policy.set_text(f"Profile: {snapshot['permission_profile']} · resumed defaults: {snapshot['effective_policy']}\n"
                            f"Workspace: {snapshot['workspace']}\nConversation: {snapshot['thread_id']}")
            level.set_value(snapshot["level"])
            mute.set_label("Resume microphone" if snapshot["muted"] else "Mute microphone")
            ptt.set_sensitive(not snapshot["muted"] and snapshot["input_mode"] == "push-to-talk")
            cancel.set_sensitive(bool(snapshot["active_turn"] or snapshot["submitting"]))
            diagnostics.set_text(f"Microphone: {snapshot['microphone_health']} · Transcription: {snapshot['transcription_health']}\n"
                                 f"Speech: {snapshot['tts_health']} · Diagnostics: jki doctor")
            if snapshot["preview_token"] and snapshot["preview_token"] != token["value"]:
                token["value"] = snapshot["preview_token"]
                transcript.set_text(snapshot["preview"])
            elif not snapshot["preview_token"] and token["value"]:
                token["value"] = ""
                transcript.set_text("")
            if snapshot["models"] != model_ids:
                updating_model["value"] = True
                model_ids[:] = snapshot["models"]
                model_menu.set_model(Gtk.StringList.new(model_ids or ["No models available"]))
                updating_model["value"] = False
            if snapshot["model"] in model_ids and model_menu.get_selected() != model_ids.index(snapshot["model"]):
                updating_model["value"] = True
                model_menu.set_selected(model_ids.index(snapshot["model"]))
                updating_model["value"] = False
            if snapshot["efforts"] != effort_ids:
                updating_effort["value"] = True
                effort_ids[:] = snapshot["efforts"]
                effort_menu.set_model(Gtk.StringList.new(effort_ids or ["No reasoning controls available"]))
                updating_effort["value"] = False
            effort_menu.set_sensitive(bool(effort_ids))
            if snapshot["effort"] in effort_ids and effort_menu.get_selected() != effort_ids.index(snapshot["effort"]):
                updating_effort["value"] = True
                effort_menu.set_selected(effort_ids.index(snapshot["effort"]))
                updating_effort["value"] = False
            new_key = json.dumps(snapshot["approvals"], sort_keys=True)
            if new_key != approval_key["value"]:
                child = approvals.get_first_child()
                while child:
                    following = child.get_next_sibling()
                    approvals.remove(child)
                    child = following
                for pending in snapshot["approvals"]:
                    expander = Gtk.Expander(label="Approval requested — review the complete details")
                    expander.set_expanded(True)
                    panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                    expander.set_child(panel)
                    view = Gtk.TextView()
                    view.set_editable(False)
                    view.set_monospace(True)
                    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
                    view.get_buffer().set_text(json.dumps({"request": pending["params"], "operation": pending["item"]}, indent=2))
                    scroll = Gtk.ScrolledWindow()
                    scroll.set_min_content_height(180)
                    scroll.set_max_content_height(280)
                    scroll.set_child(view)
                    panel.append(scroll)
                    for decision, label in (("accept", "Allow once"), ("decline", "Decline"), ("cancel", "Cancel")):
                        if decision in pending["decisions"]:
                            control = button(label, lambda i=pending["id"], d=decision: engine.resolve_approval(i, d), panel)
                            control.set_sensitive(not pending["answered"] and (decision != "accept" or pending["can_accept"]))
                    approvals.append(expander)
                approval_key["value"] = new_key
            draw_key = (snapshot["status"], round(snapshot["level"], 1))
            interval = refresh_interval(snapshot, window.get_mapped(), reduce_motion.get_active())
            if window.get_mapped() and (interval == 50 or draw_key != previous["draw"]):
                orb.queue_draw()
                previous["draw"] = draw_key
            if not demo:
                guarded(lambda: status_file.update(snapshot, engine.settings.persist_transcript))
            GLib.timeout_add(interval, refresh)
            return False
        if not demo:
            engine.start()
        else:
            from .demo import start_demo
            start_demo(engine, GLib)
        window.present()
        refresh()

    def shutdown(*_):
        running["value"] = False
        engine.close()
        status_file.close()
    app.connect("activate", activate)
    app.connect("shutdown", shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (app.quit(), False)[1])
    try:
        return app.run([])
    finally:
        running["value"] = False
        engine.close()
        status_file.close()
        os.close(fd)
