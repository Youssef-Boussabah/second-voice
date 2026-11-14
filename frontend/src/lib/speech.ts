// Playback. Only ever invoked from a user tap (see store.speakCandidate / speakTyped).
import { api } from "./api";

let current: HTMLAudioElement | null = null;
let finishCurrent: (() => void) | null = null;
// Bumped by every stop/new speak: a TTS response that arrives after the user stopped (or tapped
// something else) is discarded instead of playing late.
let generation = 0;

export function stopSpeaking() {
  generation++;
  current?.pause();
  current = null;
  finishCurrent?.(); // release the awaiting caller so the card stops "speaking"
  finishCurrent = null;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

function browserSpeak(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    finishCurrent = resolve;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    // safety: never leave the card pulsing forever
    setTimeout(resolve, 2000 + text.length * 90);
  });
}

export type Voice = "elevenlabs" | "browser" | "stopped";

/** POST /api/tts → play MP3; falls back to browser speech if the provider is down. */
export async function speak(text: string): Promise<Voice> {
  stopSpeaking();
  const mine = generation;
  const blob = await api.tts(text);
  if (mine !== generation) return "stopped";
  if (!blob) {
    await browserSpeak(text);
    return mine === generation ? "browser" : "stopped";
  }
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  current = audio;
  try {
    await new Promise<void>((resolve, reject) => {
      finishCurrent = resolve;
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error("audio playback failed"));
      audio.play().catch(reject);
    });
    return mine === generation ? "elevenlabs" : "stopped";
  } catch {
    if (mine !== generation) return "stopped";
    await browserSpeak(text);
    return "browser";
  } finally {
    URL.revokeObjectURL(url);
    if (current === audio) current = null;
  }
}
