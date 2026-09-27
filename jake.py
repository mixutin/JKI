#!/usr/bin/env python3
"""Jake: an always-listening, wake-name-gated Codex desktop companion."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from engine import Engine, STATE, load_config


def run_gui(config):
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Gtk4LayerShell', '1.0')
    from gi.repository import Gtk, Gdk, GLib, Gtk4LayerShell
    from orb import draw_orb

    STATE.mkdir(parents=True, exist_ok=True)
    lock = (STATE/'instance.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        print('Jake is already running.')
        return 0
    engine = Engine(config)
    app = Gtk.Application(application_id='local.jake.Voice')
    css = b'''
    window { background: transparent; color: #edf0ff; }
    .card { background: alpha(#101421, 0.96); border-radius: 26px;
      border: 1px solid alpha(#a1b5ff, 0.16); padding: 16px 20px 18px; }
    .brand { font-family: sans-serif; font-weight: 800; font-size: 12px;
      letter-spacing: 3px; color: #dce6ff; }
    .status { font-size: 16px; font-weight: 600; color: #eef2ff; }
    .detail { font-size: 11px; color: #97a6bd; }
    .heard { font-size: 11px; color: #c3ccdf; }
    .tiny { font-size: 10px; color: #718198; }
    button { background: alpha(#a6b7e8, 0.07); border: 1px solid alpha(#a6b7e8, 0.1);
      border-radius: 11px; box-shadow: none; min-height: 24px; color: #ccd8ee;
      font-size: 11px; padding: 5px 10px; }
    button:hover { background: alpha(#a6b7e8, 0.16); color: white; }
    .close { background: transparent; border: none; min-height: 15px; padding: 1px 5px; }
    popover contents { background: #151b2b; border: 1px solid #2c3852; border-radius: 14px; }
    '''
    start = time.monotonic()

    def activate(application):
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        window = Gtk.ApplicationWindow(application=application)
        window.set_title('Jake · Voice companion')
        window.set_decorated(False)
        window.set_resizable(False)
        window.set_default_size(296, 330)
        if Gtk4LayerShell.is_supported():
            Gtk4LayerShell.init_for_window(window)
            Gtk4LayerShell.set_namespace(window, 'jake-voice')
            Gtk4LayerShell.set_layer(window, Gtk4LayerShell.Layer.TOP)
            Gtk4LayerShell.set_keyboard_mode(window, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
            Gtk4LayerShell.set_anchor(window, Gtk4LayerShell.Edge.RIGHT, True)
            Gtk4LayerShell.set_anchor(window, Gtk4LayerShell.Edge.BOTTOM, True)
            Gtk4LayerShell.set_margin(window, Gtk4LayerShell.Edge.RIGHT, 24)
            Gtk4LayerShell.set_margin(window, Gtk4LayerShell.Edge.BOTTOM, 76)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class('card')
        window.set_child(box)
        header=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        brand=Gtk.Label(label='JAKE', xalign=0)
        brand.add_css_class('brand')
        brand.set_hexpand(True)
        header.append(brand)
        marker=Gtk.Label(label='VOICE COMPANION')
        marker.add_css_class('tiny')
        header.append(marker)
        close=Gtk.Button(label='×')
        close.add_css_class('close')
        close.set_tooltip_text('Stop Jake and release the microphone')
        close.connect('clicked', lambda *_: application.quit())
        header.append(close)
        box.append(header)
        orb=Gtk.DrawingArea()
        orb.set_content_width(250)
        orb.set_content_height(166)
        def draw(area, ctx, width, height):
            s=engine.snapshot()
            level=s['level']
            if s['status']=='speaking':level=.2+.12*__import__('math').sin(time.monotonic()*7)
            draw_orb(ctx,width,height,s['status'],time.monotonic()-start,level)
        orb.set_draw_func(draw)
        orb.set_tooltip_text('Click the orb to mute or resume listening')
        click=Gtk.GestureClick()
        click.connect('released',lambda *_: engine.toggle_mute())
        orb.add_controller(click)
        box.append(orb)
        status=Gtk.Label(label='Waking up')
        status.add_css_class('status')
        box.append(status)
        detail=Gtk.Label(label='Connecting to your conversation')
        detail.add_css_class('detail')
        detail.set_wrap(True)
        detail.set_max_width_chars(37)
        box.append(detail)
        heard=Gtk.Label(label='')
        heard.add_css_class('heard')
        heard.set_ellipsize(3)
        heard.set_max_width_chars(35)
        box.append(heard)
        controls=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=8)
        mute=Gtk.Button(label='Mute mic')
        mute.connect('clicked',lambda *_: engine.toggle_mute())
        controls.append(mute)
        model=Gtk.MenuButton(label='Astra ▾')
        model.set_hexpand(True)
        popover=Gtk.Popover()
        choices=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        choices.set_margin_top(8);choices.set_margin_bottom(8)
        choices.set_margin_start(8);choices.set_margin_end(8)
        popover.set_child(choices)
        model.set_popover(popover)
        controls.append(model)
        box.append(controls)
        chat=Gtk.Button(label='Open conversation ↗')
        chat.set_tooltip_text('Open this Codex conversation in a terminal')
        def open_chat(*_):
            subprocess.Popen(['kitty','-e',config['codex_path'],'resume',config['thread_id']],
                             start_new_session=True)
        chat.connect('clicked',open_chat)
        box.append(chat)
        previous={'models':[],'state':None}
        titles={'starting':'Waking up','listening':'Here when you need me',
                'hearing':'I’m listening','working':'On it','speaking':'Speaking',
                'muted':'Taking a quiet moment','offline':'Reconnecting',
                'attention':'Needs your attention','error':'Check the microphone'}
        def refresh():
            s=engine.snapshot()
            status.set_text(titles.get(s['status'],s['status']))
            detail.set_text('Microphone off · click to resume' if s['status']=='muted' else s['detail'])
            heard.set_text(('“'+s['heard']+'”') if s['heard'] else '')
            mute.set_label('Resume mic' if s['status']=='muted' else 'Mute mic')
            model.set_label(s['model'].removeprefix('gpt-').title()+' ▾')
            if s['models'] != previous['models']:
                child=choices.get_first_child()
                while child:
                    nxt=child.get_next_sibling();choices.remove(child);child=nxt
                for mid in s['models']:
                    button=Gtk.Button(label=mid)
                    def choose(widget,m=mid):
                        engine.select_model(m)
                        popover.popdown()
                    button.connect('clicked',choose)
                    choices.append(button)
                previous['models']=s['models']
            # Status is local and contains only commands addressed to Jake.
            state_key=(s['status'],s['detail'],s['model'],s['heard'])
            if state_key != previous['state']:
                public={k:v for k,v in s.items() if k!='level'}
                public['pid']=os.getpid()
                temp=STATE/'status.tmp'
                temp.write_text(json.dumps(public))
                temp.chmod(0o600)
                temp.replace(STATE/'status.json')
                previous['state']=state_key
            orb.queue_draw()
            return True
        GLib.timeout_add(50,refresh)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,lambda: (application.quit(),False)[1])
        engine.start()
        window.present()
    app.connect('activate',activate)
    app.connect('shutdown',lambda *_:engine.close())
    return app.run([])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',nargs='?',default='run',choices=['run','check','say'])
    parser.add_argument('--config',type=Path)
    parser.add_argument('--text',default='Voice playback is working.')
    args=parser.parse_args()
    config=load_config(args.config) if args.config else load_config()
    if args.command=='check':
        from engine import CodexClient
        from vosk import Model,SetLogLevel
        from faster_whisper import WhisperModel
        SetLogLevel(-1)
        Model(config['model_path'])
        WhisperModel(config['transcription_model_path'],device='cpu',compute_type='int8',cpu_threads=4)
        client=CodexClient(config['socket_path'],lambda event:None)
        thread=client.call('thread/read',{'threadId':config['thread_id']})['thread']
        models=client.call('model/list',{})['data']
        client.close()
        print('Wake model and command transcription model: OK')
        print('Codex thread:',thread['id'])
        print('Models:',', '.join(m['model'] for m in models))
        return 0
    if args.command=='say':
        subprocess.run(['espeak-ng','-v','en-us+m3',args.text],check=True)
        return 0
    return run_gui(config)


if __name__=='__main__':
    raise SystemExit(main())
