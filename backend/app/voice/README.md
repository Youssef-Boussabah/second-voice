# Voice integration

All shared signatures and REST bodies are unchanged. Lane A's
`on_partner_utterance(utt)` receives a persisted `Utterance(source="stt")` as a
FastAPI background task. No synthesis occurs in this pipeline. With change streams
off, the audio route broadcasts `utterance.created` directly.

Lane C: after the explicit select/typed-reply action, POST `/api/tts` with
`{"text": selectResult.text_to_speak}`. Play the returned MPEG blob. On HTTP 503
`{"fallback":"browser"}`, use `speechSynthesis.speak(new SpeechSynthesisUtterance(text))`
from that same user action. Do not call this route when cards arrive. TTSIn carries
only text, so the server cannot independently attest to a physical tap.

Audio: multipart `session_id` and `audio` (16-bit PCM WAV, 1–2 channels, 8–48 kHz,
maximum 30 seconds/4 MiB). Response is `UtteranceOut`; silence returns 204. STT
failure returns 503 for typed fallback; speaker failure returns unknown while
preserving transcription. `X-Mock-Text`/`X-Mock-Person` work only when the respective
mock flag is enabled. No raw audio is stored, including enrollment clips.

Enrollment: POST `/api/people` with explicit `consent_voice`; POST
`/api/people/{id}/enroll` with 3–10 multipart `clips[]`. Missing consent is 409.
Mock speaker mode refuses enrollment rather than storing artificial biometrics.
Responses never expose vectors. Model initialization and inference use a worker
thread; first speaker use downloads/warms ECAPA, so prewarm before a live demo.

Install core requirements first. ElevenLabs SDK 2.78.0 was inspected and exercised
using its real async client against a test HTTP transport. For speaker inference,
install compatible CPU `torch`, `torchaudio`, `speechbrain`, `soundfile`, and `scipy`.
Speaker identification uses Atlas `people_voice` (192-d, cosine), configured score
threshold and 0.03 top-two margin. Session continuity relaxes the threshold by 0.05
only for the same speaker in the same session within 30 seconds. Unknown voiceprints
are discarded. Design reference: [Amelia](https://github.com/borisnezlobin/mongo-hacks);
this is an independent implementation, with no copied Amelia source.

Use `backend/scripts/voice_enroll_seed.py` for consented local enrollment and
`backend/scripts/voice_calibrate.py` with separate held-out clips to report real
scores. No preset accuracy or latency claims are made. `/api/voice/status` reports
configured mock modes and detects missing configuration/dependencies (503); it
does not make paid provider health probes. Run `backend/scripts/voice_model_check.py`
to prewarm and verify real model operation on synthetic audio before the demo.

Run from repo root (PowerShell):

```powershell
$env:PYTHONPATH='backend'
.venv/Scripts/python.exe -m pytest -q backend/tests/test_b_voice.py
```

Provider tests use HTTP substitutes; database tests use async substitutes. Live
Atlas, ElevenLabs synthesis/transcription, consenting cloned voice playback and
noisy-room speaker accuracy must be verified with real configured services.
