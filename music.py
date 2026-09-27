"""Desktop media shortcuts. Song search uses the installed mpv/yt-dlp tools."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time


def music_query(text):
    if re.search(r'\bon (?:spotify|youtube|apple music)\b', text):
        return None  # Let Codex fulfill an explicitly chosen app request.
    match=re.match(r'^play (?:the )?(?:song|track|music)(?: called)? (.+)$',text)
    if match:
        return match.group(1).strip(' .!?')
    if text.startswith('play ') and ' by ' in text:
        return text[5:].strip(' .!?')
    return None


class MediaController:
    def __init__(self, say):
        self.say=say
        self.process=None
        self.socket_path=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'jake-music.sock'

    def _ipc(self,command):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(self.socket_path))
            connection.sendall((json.dumps({'command':command,'request_id':1})+'\n').encode())
            with connection.makefile('rb') as reader:
                for line in reader:
                    response=json.loads(line)
                    if response.get('request_id')==1:
                        if response.get('error')!='success':raise RuntimeError(response.get('error'))
                        return response.get('data')
        raise RuntimeError('Music player did not respond')

    def handle(self,text):
        query=music_query(text)
        if query:
            self.play(query)
            return True
        actions={'pause music':('set_property','pause',True),
                 'pause the music':('set_property','pause',True),
                 'resume music':('set_property','pause',False),
                 'resume the music':('set_property','pause',False),
                 'play music':('set_property','pause',False),
                 'stop music':('stop',),'stop the music':('stop',),
                 'next song':('playlist-next','force'),'next track':('playlist-next','force'),
                 'skip song':('playlist-next','force'),'skip this song':('playlist-next','force'),
                 'previous song':('playlist-prev','force'),'previous track':('playlist-prev','force')}
        if text in actions:
            action=actions[text]
            try:
                if self.process and self.process.poll() is None:
                    if action[0].startswith('playlist-'):
                        self.say('This is a single requested track. Ask me for the next song by name.')
                    else:
                        self._ipc(list(action))
                else:
                    command=('pause' if action==('set_property','pause',True) else
                             'play' if action==('set_property','pause',False) else
                             'next' if action[0]=='playlist-next' else
                             'previous' if action[0]=='playlist-prev' else 'stop')
                    result=subprocess.run(['playerctl',command],capture_output=True,text=True,timeout=5)
                    if result.returncode:
                        self.say('No active music player was found. Ask me to play a song by name.')
            except Exception:
                self.say('The music player did not respond.')
            return True
        volume={'volume up':'5%+','turn the volume up':'5%+','turn volume up':'5%+',
                'volume down':'5%-','turn the volume down':'5%-','turn volume down':'5%-'}
        if text in volume:
            subprocess.run(['wpctl','set-volume','-l','1.0','@DEFAULT_AUDIO_SINK@',volume[text]],check=True,timeout=5)
            return True
        match=re.match(r'^(?:set )?(?:the )?volume (?:to )?(\d{1,3})(?: ?percent| ?%)?$',text)
        if match:
            amount=min(100,int(match.group(1)))
            subprocess.run(['wpctl','set-volume','@DEFAULT_AUDIO_SINK@',f'{amount}%'],check=True,timeout=5)
            return True
        return False

    def play(self,query):
        self.close()
        self.say('Looking for '+query+'.')
        process=subprocess.Popen(['mpv','--no-video','--force-window=no','--no-terminal',
            '--input-ipc-server='+str(self.socket_path),'--ytdl-format=bestaudio/best',
            '--','ytdl://ytsearch1:'+query],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.process=process
        def watch():
            _,error=process.communicate()
            if process.returncode and process.returncode > 0 and self.process is process:
                print('Music playback:',error.decode(errors='replace')[-800:],flush=True)
                self.say('I could not play that track. You can ask me to try it in Spotify.')
        threading.Thread(target=watch,daemon=True).start()

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill()
        self.process=None
