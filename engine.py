"""Local microphone recognition and a voice bridge to an existing Codex thread."""
from __future__ import annotations

import array
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parent
CONFIG = Path.home() / '.config/jake-voice/config.json'
STATE = Path.home() / '.local/state/jake-voice'


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text())


def save_config(config, path=CONFIG):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(config, indent=2) + '\n')
    temp.chmod(0o600)
    temp.replace(path)


def speakable(text):
    text = re.sub(r'```[\s\S]*?```', ' Code is available in the chat. ', text)
    text = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', 'link in the chat', text)
    text = re.sub(r'(?m)^\s*[#>*-]+\s*', '', text)
    text = re.sub(r'[`*_~]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > 1600:
        cut = text.rfind('. ', 800, 1500)
        text = text[:cut + 1 if cut != -1 else 1500] + ' The rest is in the chat.'
    return text


class WakeGate:
    """Only a whole-word wake name, or one follow-up after it, opens the gate."""
    def __init__(self, name='jake', grace=12):
        self.pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.I)
        self.grace = grace
        self.armed_until = 0.0

    def reset(self):
        self.armed_until = 0.0

    def accept(self, text, now=None, words=None):
        now = time.monotonic() if now is None else now
        text = text.strip()
        match = self.pattern.search(text)
        if match:
            if words is not None:
                confidence = [w.get('conf', 1) for w in words
                              if self.pattern.fullmatch(w.get('word', ''))]
                if confidence and max(confidence) < 0.65:
                    return None
            text = self.pattern.sub('', text)
            text = re.sub(r'^\s*(?:hey|hi|hello|okay|ok)[,\s]+', '', text, flags=re.I)
            text = text.strip(' ,.!?')
            if not text:
                self.armed_until = now + self.grace
                return ''
            self.reset()
            return text
        if text and now < self.armed_until:
            self.reset()
            return text
        return None


def model_choice(command, models):
    """Resolve an explicit model request against the account's actual catalog."""
    text = command.lower().strip(' .!?')
    if not re.match(r'^(?:please\s+)?(?:switch|change|use|select|set)\b', text):
        return None
    if not re.search(r'\b(?:model|astra|astro|astral|sol|soul|seoul|luna|lunar|terra|tara|gpt|g p t)\b', text):
        return None
    versions = [(r'five\s+(?:point|dot)\s+six|5[ .]6', '5.6'),
                (r'five\s+(?:point|dot)\s+five|5[ .]5', '5.5'),
                (r'\bsix\b|\b6\b', '6')]
    version = next((v for pattern, v in versions if re.search(pattern, text)), None)
    aliases = {'astra': r'\b(?:astra|astro|astral)\b',
               'sol': r'\b(?:sol|soul|seoul)\b',
               'luna': r'\b(?:luna|lunar)\b',
               'terra': r'\b(?:terra|tara)\b'}
    family = next((f for f, pattern in aliases.items() if re.search(pattern, text)), None)
    candidates = [m for m in models if (not family or m.endswith('-' + family))
                  and (not version or m == 'gpt-' + version or m.startswith('gpt-' + version + '-'))]
    if not family and not version:
        return ''
    if not candidates:
        return ''
    # The account catalog orders its current recommendations first.
    return candidates[0] if family or len(candidates) == 1 else ''


def effort_choice(command, efforts):
    """Resolve a spoken reasoning effort only when it is an explicit setting."""
    text = command.lower().strip(' .!?')
    if not re.search(r'\b(?:reasoning|effort|thinking)\b', text):
        return None
    names = sorted(set(efforts), key=len, reverse=True)
    aliases = {'xhigh': r'\b(?:extra\s*high|x\s*high|xhigh)\b'}
    for effort in names:
        pattern = aliases.get(effort, r'\b' + re.escape(effort) + r'\b')
        if re.search(pattern, text):
            return effort
    return ''


class CodexClient:
    """One local WebSocket, concurrent RPC requests, and live notifications."""
    def __init__(self, socket_path, callback):
        from websockets.sync.client import unix_connect
        self.ws = unix_connect(socket_path, uri='ws://localhost/', open_timeout=10,
                               max_size=32 * 1024 * 1024)
        self.callback = callback
        self.pending = {}
        self.lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.closed = threading.Event()
        self.seq = 0
        threading.Thread(target=self._read, daemon=True).start()
        self.call('initialize', {
            'clientInfo': {'name': 'jake_voice', 'version': '1.0.0'},
            'capabilities': {'experimentalApi': True}})
        with self.write_lock:
            self.ws.send(json.dumps({'method': 'initialized', 'params': {}}))

    def _read(self):
        try:
            for raw in self.ws:
                obj = json.loads(raw)
                if 'id' in obj and 'method' not in obj:
                    with self.lock:
                        waiter = self.pending.get(obj['id'])
                    if waiter:
                        waiter.put(obj)
                elif 'method' in obj:
                    # Approval requests remain for the user's Codex client.
                    self.callback(obj)
        except Exception as exc:
            self.callback({'method': 'jake/disconnected', 'params': {'message': str(exc)}})
        finally:
            self.closed.set()
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put({'error': {'message': 'Codex connection closed'}})

    def call(self, method, params, timeout=20):
        waiter = queue.Queue()
        with self.lock:
            self.seq += 1
            number = self.seq
            self.pending[number] = waiter
        try:
            with self.write_lock:
                self.ws.send(json.dumps({'id': number, 'method': method, 'params': params}))
            try:
                obj = waiter.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f'Codex did not answer {method}') from None
            if 'error' in obj:
                raise RuntimeError(str(obj['error'].get('message', obj['error'])))
            return obj['result']
        finally:
            with self.lock:
                self.pending.pop(number, None)

    def close(self):
        self.ws.close()
        self.closed.set()


class Engine:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.muted = threading.Event()
        self.speaking = threading.Event()
        self.gate = WakeGate(config.get('wake_word', 'jake'))
        self.client = None
        self.recorder = None
        self.player = None
        self.commands = queue.Queue()
        self.recognitions = queue.Queue()
        self.speech = queue.Queue()
        self.seen_items = set()
        self.turn_messages = {}
        self.models = []
        self.model_catalog = []
        self.level = 0.0
        self.status = 'starting'
        self.detail = 'Connecting to your conversation'
        self.model = config.get('model', 'gpt-6-astra')
        self.effort = config.get('effort', 'medium')
        self.last_heard = ''
        self.working = False
        self.quiet_until = 0.0
        self.music = None

    def update(self, status=None, detail=None):
        with self.lock:
            if status is not None:
                self.status = status
            if detail is not None:
                self.detail = detail

    def snapshot(self):
        with self.lock:
            status = 'muted' if self.muted.is_set() else ('speaking' if self.speaking.is_set() else self.status)
            return {'status': status, 'detail': self.detail, 'model': self.model,
                    'models': list(self.models), 'model_catalog': list(self.model_catalog),
                    'effort': self.effort, 'level': self.level,
                    'heard': self.last_heard, 'connected': self.client is not None}

    def ready(self):
        if self.client is None:
            self.update('offline', 'Reconnecting to Codex')
        elif self.working:
            self.update('working', 'Working on your request')
        else:
            self.update('listening', 'Say “Jake” and your command')

    def start(self):
        for fn in [self._connect_loop, self._microphone_loop, self._transcription_loop,
                   self._command_loop, self._speech_loop]:
            threading.Thread(target=fn, daemon=True).start()

    def _connect_loop(self):
        while not self.stopping.is_set():
            client = None
            try:
                client = CodexClient(self.config['socket_path'], self._event)
                models = client.call('model/list', {})['data']
                self.model_catalog = [m for m in models if not m.get('hidden', False)]
                self.models = [m['model'] for m in self.model_catalog]
                params = {'threadId': self.config['thread_id'], 'excludeTurns': True,
                          'model': self.config.get('model', self.model)}
                if self.config.get('full_access'):
                    params.update(sandbox='danger-full-access', approvalPolicy='on-request')
                client.call('thread/resume', params)
                # A live resumed thread may report its previous model even when
                # resume was given an override. The next turn carries our saved
                # selection explicitly, so keep local state authoritative here.
                self.model = self.config.get('model', self.model)
                self.effort = self.config.get('effort', self.effort)
                self.client = client
                self.ready()
                print('Connected to Codex; wake name: Jake; model:', self.model, flush=True)
                while not self.stopping.is_set() and not client.closed.wait(1):
                    pass
            except Exception as exc:
                print('Codex connection:', exc, flush=True)
                self.update('offline', 'Codex is reconnecting')
            finally:
                self.client = None
                if client:
                    client.close()
            self.stopping.wait(5)

    def _event(self, event):
        method, params = event.get('method', ''), event.get('params', {})
        if params.get('threadId') not in (None, self.config['thread_id']):
            return
        if method == 'item/completed':
            item = params.get('item', {})
            if item.get('type') != 'agentMessage':
                return
            self.turn_messages[params.get('turnId')] = item
            if item.get('phase') == 'final_answer':
                self._answer(item)
        elif method == 'turn/completed':
            self.working = False
            turn = params.get('turn', {})
            item = self.turn_messages.pop(turn.get('id'), None)
            if turn.get('status') == 'completed' and item and item.get('phase') != 'commentary':
                self._answer(item)
            self.ready()
        elif method.endswith('/requestApproval'):
            self.update('attention', 'Review the approval in Codex')
            self.say('Please review the approval request in Codex.')
        elif method == 'jake/disconnected':
            self.update('offline', 'Reconnecting to Codex')

    def _answer(self, item):
        if item.get('id') in self.seen_items:
            return
        self.seen_items.add(item.get('id'))
        self.working = False
        if item.get('text'):
            self.say(item['text'])

    def say(self, text):
        cleaned = speakable(text)
        if cleaned:
            self.speech.put(cleaned)

    def _speech_loop(self):
        piper_voice = None
        piper_model = self.config.get('tts_model_path')
        if self.config.get('tts_engine') == 'piper' and piper_model:
            try:
                from piper import PiperVoice
                piper_voice = PiperVoice.load(piper_model, use_cuda=False)
                print('Loaded Piper speech model:', Path(piper_model).name, flush=True)
            except Exception as exc:
                print('Piper speech model unavailable; using eSpeak NG:', exc, flush=True)
        while not self.stopping.is_set():
            try:
                text = self.speech.get(timeout=0.5)
            except queue.Empty:
                continue
            self.speaking.set()
            self.gate.reset()
            try:
                with tempfile.TemporaryDirectory(prefix='jake-speech-') as directory:
                    wav = str(Path(directory) / 'reply.wav')
                    if piper_voice is not None:
                        with wave.open(wav, 'wb') as wav_file:
                            piper_voice.synthesize_wav(text, wav_file)
                    else:
                        subprocess.run(['espeak-ng', '--stdin', '-v', self.config.get('voice', 'en-us+m3'),
                                        '-s', '178', '-w', wav], input=text, text=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       timeout=30, check=True)
                    if self.stopping.is_set():
                        break
                    self.player = subprocess.Popen(['pw-play', wav], stderr=subprocess.DEVNULL)
                    self.player.wait(timeout=180)
            except Exception as exc:
                print('Speech playback:', exc, flush=True)
            finally:
                self.player = None
                self.quiet_until = time.monotonic() + 0.45
                self.speaking.clear()
                self.ready()

    def toggle_mute(self):
        if self.muted.is_set():
            self.muted.clear()
            self.ready()
        else:
            self.muted.set()
            self.gate.reset()
            self.detail = 'Microphone off · click to resume'
            self.stop_speaking()
            if self.recorder and self.recorder.poll() is None:
                self.recorder.terminate()

    def stop_speaking(self):
        while True:
            try:
                self.speech.get_nowait()
            except queue.Empty:
                break
        if self.player and self.player.poll() is None:
            self.player.terminate()

    def submit(self, text):
        self.commands.put(('command', text))

    def select_model(self, model):
        self.commands.put(('model', model))

    def select_effort(self, effort):
        self.commands.put(('effort', effort))

    def supported_efforts(self, model=None):
        model = model or self.model
        entry = next((item for item in self.model_catalog if item.get('model') == model), {})
        return [item.get('reasoningEffort') for item in entry.get('supportedReasoningEfforts', [])
                if item.get('reasoningEffort')]

    def _command_loop(self):
        from music import MediaController
        self.music = MediaController(self.say)
        while not self.stopping.is_set():
            try:
                kind, text = self.commands.get(timeout=0.5)
            except queue.Empty:
                continue
            self.last_heard = text
            try:
                if kind == 'model':
                    self._switch_model(text)
                    continue
                if kind == 'effort':
                    self._switch_effort(text)
                    continue
                plain = text.lower().strip(' .!?')
                if plain in {'mute', 'pause listening', 'stop listening', 'mute microphone', 'go to sleep'}:
                    if not self.muted.is_set():
                        self.toggle_mute()
                    self.say('Microphone muted. Click the orb to listen again.')
                    continue
                if plain in {'what model are you using', 'which model are you using', 'what model', 'current model'}:
                    self.say('The current model is ' + self.model + '.')
                    continue
                if plain in {'list models', 'show models', 'what models are available'}:
                    self.say('Available models: ' + ', '.join(self.models))
                    continue
                if self.music.handle(plain):
                    self.ready()
                    continue
                choice = model_choice(text, self.models)
                if choice is not None:
                    if choice:
                        self._switch_model(choice)
                        requested_effort = effort_choice(text, self.supported_efforts())
                        if requested_effort:
                            self._switch_effort(requested_effort)
                        elif requested_effort == '':
                            self.say('That model does not support the requested reasoning effort.')
                    else:
                        self.say('Please name a model from the model menu, for example, switch to Sol.')
                    continue
                effort = effort_choice(text, self.supported_efforts())
                if effort is not None:
                    if effort:
                        self._switch_effort(effort)
                    else:
                        self.say('Please choose a reasoning effort from the menu, such as medium or high.')
                    continue
                if not self.client:
                    self.say('Codex is reconnecting. Please try that command again shortly.')
                    continue
                self.working = True
                self.update('working', 'Sending your request to Codex')
                prompt = ('[Spoken command via Jake. The user addressed you by your wake name. '
                          'Reply concisely for spoken playback; perform the requested work. '
                          'The user has requested desktop, application, and music control. '
                          'Use the local app and media tools for these requests.]\n' + text)
                # This starts an idle thread or steers its current turn. No shell
                # interpolation and no automatic retries of user actions.
                self.client.call('turn/start', {'threadId': self.config['thread_id'],
                    'clientUserMessageId': str(uuid.uuid4()),
                    'model': self.model, 'effort': self.effort,
                    'input': [{'type': 'text', 'text': prompt}]})
                self.update('working', 'Working on your request')
            except Exception as exc:
                print('Voice request:', exc, flush=True)
                self.working = False
                self.update('attention', 'Could not send · try again')
                self.say('That request could not be completed. Please check the chat before trying again.')

    def _switch_model(self, model):
        if model not in self.models:
            raise ValueError('That model is not in your Codex catalog')
        if not self.client:
            raise RuntimeError('Codex is disconnected')
        self.client.call('thread/resume', {'threadId': self.config['thread_id'],
                                           'excludeTurns': True, 'model': model})
        self.model = model
        allowed = self.supported_efforts(self.model)
        if self.effort not in allowed:
            self.effort = next((level for level in ('medium', 'low') if level in allowed),
                               allowed[0] if allowed else 'medium')
        self.config['model'] = self.model
        self.config['effort'] = self.effort
        save_config(self.config)
        self.say('Using ' + self.model + ' with ' + self.effort + ' reasoning for your next request.')
        self.ready()

    def _switch_effort(self, effort):
        allowed = self.supported_efforts()
        if effort not in allowed:
            raise ValueError('That reasoning effort is not supported by the selected model')
        self.effort = effort
        self.config['effort'] = effort
        save_config(self.config)
        self.say('Reasoning effort set to ' + effort + ' for your next request.')
        self.ready()

    def _transcription_loop(self):
        try:
            import numpy as np
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
            model = WhisperModel(self.config['transcription_model_path'], device='cpu',
                                 compute_type='int8', cpu_threads=4, num_workers=1)
        except Exception as exc:
            self.update('error', 'Command speech model could not load')
            print('Command transcription:', exc, flush=True)
            return
        while not self.stopping.is_set():
            try:
                audio = self.recognitions.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.muted.is_set():
                continue
            try:
                self.update('hearing', 'Understanding your command…')
                samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
                segments, _ = model.transcribe(samples, language='en', beam_size=3,
                    vad_filter=True, condition_on_previous_text=False,
                    initial_prompt='Names and model names: Jake, GPT-6 Astra, GPT-6 Sol, GPT-6 Luna, GPT-5.6 Terra.')
                text=' '.join(s.text.strip() for s in segments
                              if s.no_speech_prob < .65 and s.avg_logprob > -1.0).strip()
                text=self.gate.pattern.sub('', text)
                text=re.sub(r'^\s*(?:hey|hi|hello|okay|ok)[,\s]+', '', text, flags=re.I).strip(' ,.!?')
                if text and not self.muted.is_set():
                    self.submit(text)
                else:
                    self.ready()
            except Exception as exc:
                print('Transcription failed:', exc, flush=True)
                self.say('I could not understand that command. Please try again.')
                self.ready()

    def _microphone_loop(self):
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            model = Model(self.config['model_path'])
        except Exception as exc:
            self.update('error', 'Speech model could not load')
            print('Speech model:', exc, flush=True)
            return
        while not self.stopping.is_set():
            if self.muted.is_set():
                self.stopping.wait(0.2)
                continue
            rec = KaldiRecognizer(model, 16000)
            rec.SetWords(True)
            suppressed = False
            utterance = bytearray()
            try:
                self.recorder = subprocess.Popen([
                    'pw-record', '--raw', '--rate', '16000', '--channels', '1',
                    '--format', 's16', '--latency', '100ms',
                    '--properties', '{ application.name = "Jake Voice" media.name = "Jake microphone" }', '-'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                while not self.stopping.is_set() and not self.muted.is_set():
                    chunk = self.recorder.stdout.read(3200)
                    if not chunk:
                        break
                    samples = array.array('h', chunk[:len(chunk)//2*2])
                    rms = math.sqrt(sum(x*x for x in samples) / max(1, len(samples))) / 32768
                    self.level = min(1.0, rms * 8)
                    if self.speaking.is_set() or time.monotonic() < self.quiet_until:
                        suppressed = True
                        utterance.clear()
                        continue
                    if suppressed:
                        rec.Reset()
                        suppressed = False
                    utterance.extend(chunk)
                    if len(utterance) > 16000 * 2 * 45:
                        # Bound memory while someone speaks without pausing.
                        del utterance[:-16000 * 2 * 45]
                    if rec.AcceptWaveform(chunk):
                        result = json.loads(rec.Result())
                        command = self.gate.accept(result.get('text', ''), words=result.get('result'))
                        if command == '':
                            self.update('hearing', 'I’m listening…')
                        elif command is not None:
                            self.recognitions.put(bytes(utterance))
                        elif self.status == 'hearing' and time.monotonic() >= self.gate.armed_until:
                            self.ready()
                        utterance.clear()
                    else:
                        partial = json.loads(rec.PartialResult()).get('partial', '')
                        if self.gate.pattern.search(partial):
                            self.update('hearing', 'I’m listening…')
            except Exception as exc:
                print('Microphone:', exc, flush=True)
            finally:
                if self.recorder:
                    if self.recorder.poll() is None:
                        self.recorder.terminate()
                    try:
                        self.recorder.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.recorder.kill()
                    self.recorder = None
            if not self.muted.is_set() and not self.stopping.is_set():
                self.update('error', 'Microphone unavailable · retrying')
                self.stopping.wait(3)

    def close(self):
        self.stopping.set()
        self.stop_speaking()
        if self.recorder and self.recorder.poll() is None:
            self.recorder.terminate()
        if self.client:
            self.client.close()
        if self.music:
            self.music.close()
