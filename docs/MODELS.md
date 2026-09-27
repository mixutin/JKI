# Explicit, verified model installation

Runtime does not download model weights. Configure a local Whisper directory or an already-cached
model name. Vosk is only required in wake-word mode. Piper requires a voice ONNX file and adjacent
`.onnx.json` file; eSpeak is the fallback. Models must match the chosen language. An English-only
Whisper model is rejected for a non-English/auto language setting.

```sh
jki models --manifest /absolute/path/to/trusted-model-manifest.json
jki setup
```

The installer validates HTTPS URLs, exact byte lengths and SHA-256 hashes before publishing a
complete directory. ZIP extraction rejects traversal, symlinks, duplicate entries, overlaps, and
excessive expanded size. Limits are 100 manifest files, 10,000 ZIP entries and 3 GiB total download/
expanded installation size. An existing destination is not silently replaced.

Manifest shape (this is a template, deliberately not an installable download catalog):

```json
{
  "schema_version": 1,
  "id": "a-versioned-model-id",
  "files": [
    {
      "path": "model.bin",
      "url": "https://MODEL-PUBLISHER/IMMUTABLE-REVISION/model.bin",
      "size": "REPLACE_WITH_EXACT_INTEGER_BYTE_LENGTH",
      "sha256": "REPLACE_WITH_VERIFIED_64_CHARACTER_SHA256"
    }
  ]
}
```

Add `"archive": "zip"` to download a ZIP and extract it under the supplied path. Supply every
required file, including tokenizer/config/vocabulary companions. A trustworthy digest source matters:
a hash obtained from the same compromised download is not independent authenticity verification.

A curated manifest catalog and native tests for English/Finnish voice sets are **remaining work**.
The implementation does not invent checksums, license permissions, or language-quality claims.
