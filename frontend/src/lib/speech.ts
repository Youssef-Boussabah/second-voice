// Playback. Only ever invoked from a user tap (see store.speakCandidate / speakTyped).
import { api } from "./api";

let current: HTMLAudioElement | null = null;

export function stopSpeaking() {
  current?.pause();
  current = null;
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

function browserSpeak(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (!("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    // safety: never leave the card pulsing forever
    setTimeout(resolve, 2000 + text.length * 90);
  });
}

/** POST /api/tts → play MP3; falls back to browser speech if the provider is down. */
export async function speak(text: string): Promise<"elevenlabs" | "browser"> {
  stopSpeaking();
  const blob = await api.tts(text);
  if (!blob) {
    await browserSpeak(text);
    return "browser";
  }
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  current = audio;
  try {
    await new Promise<void>((resolve, reject) => {
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error("audio playback failed"));
      audio.play().catch(reject);
    });
    return "elevenlabs";
  } catch {
    await browserSpeak(text);
    return "browser";
  } finally {
    URL.revokeObjectURL(url);
    if (current === audio) current = null;
  }
}
