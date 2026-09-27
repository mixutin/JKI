# Performance measurements

There is no claim of measured end-to-end speedup in this proposal. The source includes bounded,
transcript-free timing buffers and a repeatable benchmark command. The checked-in synthetic result
in `reports/synthetic-benchmark.json` measures only engine orchestration on its recorded environment;
it is not an ASR, GPU, GUI, energy, or Codex latency benchmark.

```sh
jki benchmark --config /absolute/config.json --iterations 500
jki benchmark --config /absolute/config.json --wav /path/to/16k-mono-s16.wav --iterations 5
```

The WAV mode runs the configured offline Whisper worker, reports cold and warm transcription times,
and never prints the transcript. Use a recording the contributor is authorized to process. Record
hardware, model/revision, language, sample duration, thread count, compute type, and background load.
The container report is not a reference desktop. A desktop CPU, memory, battery, cold-start and
end-of-utterance-to-first-audio baseline still needs to be collected.

Runtime metrics include submission acknowledgment, task duration, transcription, speech queue to
playback, and playback duration. Metrics are accessible through the engine snapshot; they are not
persisted automatically. The GUI uses 50 ms active updates, 250 ms static/reduced-motion updates,
and 1000 ms when unmapped. No orb drawing is scheduled when unmapped. Native rendering tests are
still necessary to quantify actual CPU impact.

Do not present task plan step counts as a completion percentage. Backend/model latency and local
recognition/playback latency must be reported separately.
