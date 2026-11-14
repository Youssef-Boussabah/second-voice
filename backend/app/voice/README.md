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
thread; startup warms ECAPA in a background task without delaying the app. First
speaker use also lazily initializes it if needed; prewarm before a live demo.

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

Automated provider tests use HTTP substitutes; automated database tests use async
substitutes. Run the explicitly paid live verification separately:

```powershell
.venv/Scripts/python.exe backend/scripts/voice_verify_live.py
```

This uses real ElevenLabs TTS/STT, routes mounted on `app.main`, and real Atlas
persistence. It overrides TTS/STT mock flags only within that process, uploads
generated speech, and cleans up its unique synthetic user/session records. Use
`--isolated-db` only when Atlas is unavailable; that result explicitly reports
substitute persistence. Generated MP3s stay under ignored `.models/voice-verification`.
It never prints credentials, provider response bodies, or configured voice IDs.

Live verification passed on 2026-11-14 with the configured ElevenLabs voice:

- SDK TTS and `POST /api/tts` generated MP3s that fully decoded to non-silent
  44.1 kHz audio (approximately 3.4 seconds). Saved samples are available for listening.
- Real Scribe correctly transcribed "Hello Maya. The garden looks lovely today."
  after conversion to 16-kHz mono PCM WAV; comparison ignores case/punctuation.
- `POST /api/utterances/audio` returned 200 with `source=stt`, persisted the real
  transcript in Atlas, and dispatched to A's pipeline interface. That interface
  is still a stub on this branch; suggestion generation is not verified here.
- Latest observed timings: SDK first audio 784 ms; complete TTS route 556 ms;
  SDK STT 586 ms; audio-route STT 691 ms and total 870 ms. These are individual
  observations, not benchmark percentiles or guarantees.
- Speaker mode was explicitly mocked to unknown/manual fallback. No consented
  recordings were available, so real enrollment, identity matching and noisy-room
  accuracy remain unverified. Generated speech was not enrolled as a real person.

The existing local `.env` still enables `MOCK_TTS` and `MOCK_STT`. For live normal
server startup, set both to `0` in the server process environment (or local config).
Credentials and config were not changed or committed by the verifier. The physical
speaker/listening path and frontend playback still need a user-tap check in the UI.

Local verification: SpeechBrain 1.1.2, CPU Torch 2.15.0 and torchaudio 2.11.1
successfully loaded the public ECAPA model and produced a finite, normalized
192-dimensional vector from synthetic audio via `voice_model_check.py`. Model
files use `COPY_SKIP_CACHE` in the ignored `.models/ecapa` directory, avoiding
Windows symlink privileges. This checks model operation, not recognition accuracy.
