"""Render an actual GTK fixture without using a microphone or backend (run under Xvfb)."""
from pathlib import Path
import os
import tempfile


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        for name in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME'):
            os.environ[name] = directory + '/' + name
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk, GLib
        from jki.config import Settings
        from jki.demo import DemoEngine
        from jki.ui import run_gui
        observed = {'window': False}
        def quit_fixture():
            app = Gtk.Application.get_default()
            if app:
                observed['window'] = bool(app.get_windows())
                app.quit()
            return False
        GLib.timeout_add(6500, quit_fixture)
        engine = DemoEngine(Settings(thread_id='demo'), Path(directory) / 'config.json')
        assert run_gui(engine, demo=True) == 0
        assert observed['window'], 'No native GTK window was constructed'
        assert not engine.threads and engine.audio is None, 'Demo started a hardware worker'


if __name__ == '__main__':
    main()
