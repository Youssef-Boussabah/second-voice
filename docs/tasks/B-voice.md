# Lane B: Voice (PC1 · Codex)

> **URGENT 5:00 PM SUBMISSION OVERRIDE**: Start by reading `LAUNCH_NOW.md` in the repository root. Original task timings and 6:30 submission assumptions are superseded. Reach a working P0 flow by 1:30 PM; prioritize the lane-specific order in `LAUNCH_NOW.md` ahead of later steps here. Commit and push usable partial functionality often. Avoid blocking any teammate on an unfinished optional dependency.


## Kickoff prompt (paste into Codex)
> You are Lane B ("Voice") of Second Voice. Read `AGENTS.md`, `docs/02-architecture.md`, `docs/04-api-contracts.md` (Lane B sections and §4), `backend/app/contracts.py`, and this file. You own `backend/app/voice/`, `backend/app/api/voice_routes.py`, `backend/scripts/voice_*`, `backend/tests/test_b_*`. Build in the order below, honour the `MOCK_STT`, `MOCK_SPEAKER` and `MOCK_TTS` flags, run your tests after each step, and commit with a `[B]` prefix. Don't edit other lanes' files. Call Lane A only through `app.graph.pipeline.on_partner_utterance` (a stub exists).

## Build order
1. **TTS first** (20 min; Checkpoint 1 needs it). `voice/tts.py: speak_stream(text) -> AsyncIterator[bytes]` using the ElevenLabs Python SDK: `client.text_to_speech.stream(voice_id=settings.elevenlabs_voice_id, text=text, model_id=settings.tts_model, output_format="mp3_44100_128")`. Check the SDK's exact method name. Wrap sync iterators with `asyncio.to_thread`. Route `POST /api/tts` → `StreamingResponse(media_type="audio/mpeg")`. `MOCK_TTS=1` → return 503 with `{"fallback":"browser"}` so the frontend uses `speechSynthesis`.
2. **STT** (20 min). `voice/stt.py: transcribe(wav_bytes) -> str` via `client.speech_to_text.convert(file=BytesIO(wav), model_id=settings.stt_model, language_code="eng")`. Add `keyterms` from people names ("Dana", "Maya", "Leafs", …) if the SDK supports it. `MOCK_STT=1` → return the `X-Mock-Text` header or "Hi Maya, how are you?".
3. **Speaker embedding** (40 min). `voice/speaker.py`:
   - Load `speechbrain.inference.speaker.EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb", savedir=".models/ecapa")` **once** at startup (lazy singleton, warm it with 1 s of silence).
   - `embed_voice(wav)`: decode with `soundfile`, mono, resample to 16 kHz if needed, `encode_batch`, flatten → 192-d, L2-normalize. Run in `asyncio.to_thread`.
   - `identify(user_id, wav)`: `$vectorSearch` on `people` index `people_voice`, path `voice_centroid`, filter `{user_id}`, `limit 3`, `numCandidates 20`, project `vectorSearchScore`. Match if top score ≥ `SPEAKER_THRESHOLD` (start 0.80; Atlas cosine score = (1+cos)/2) **and** margin over #2 ≥ 0.03. Session-sticky rule from `02-architecture.md` step 3. Return `SpeakerMatch`.
   - `MOCK_SPEAKER=1` → return the `X-Mock-Person` header's person or `unknown`.
4. **Enrollment** (20 min). `POST /api/people` (requires `consent_voice` true to accept clips later) and `POST /api/people/{id}/enroll` with 3+ clips → voiceprints + centroid. 409 if no consent. Script `scripts/voice_enroll_seed.py` enrolls everyone from `seed/voices/<person_id>/*.wav`.
5. **Audio utterance route** (20 min). `POST /api/utterances/audio`: run `asyncio.gather(transcribe, identify)`, insert `Utterance(source="stt", speaker=...)`, optionally store the clip in `audio_clips` (TTL), `create_task(on_partner_utterance(utt))`, return `UtteranceOut` with per-step latency. Empty transcript → 204, no utterance.
6. **Calibration tool** `scripts/voice_calibrate.py`: for each enrolled person, score held-out clips against all centroids and print a confusion table plus a suggested threshold. Run it at Checkpoint 2 and put the number in `.env`.

## Acceptance (Checkpoint 2)
Dana speaks into the tablet → `utterance.created` shows `person_id=per_dana`, score ≥ threshold, transcript correct, STT+ID ≤ 900 ms. Tap → Maya's cloned voice plays within ~600 ms.

## Watch-outs
Torch is a big install, so start `pip install` immediately. Use the CPU wheels: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`. If SpeechBrain breaks on the installed torchaudio, pin `torchaudio` to the version SpeechBrain's README names. Don't change the 192-d embedding size; index #1 depends on it.
