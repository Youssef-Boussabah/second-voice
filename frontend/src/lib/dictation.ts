// Browser speech-to-text (Web Speech API) used to *fill the text box* with what the partner said.
// The text is never sent until the user taps Send. Falls back gracefully when unsupported.
interface SRResultEvent { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }
interface SR {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: SRResultEvent) => void) | null; onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
  start(): void; stop(): void;
}
type SRCtor = new () => SR;

const Ctor: SRCtor | undefined =
  (window as unknown as { SpeechRecognition?: SRCtor }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: SRCtor }).webkitSpeechRecognition;

export const dictationSupported = !!Ctor;

export function startDictation(onText: (text: string, final: boolean) => void, onEnd: (err?: string) => void): () => void {
  if (!Ctor) {
    onEnd("Speech recognition isn't supported in this browser");
    return () => undefined;
  }
  const r = new Ctor();
  r.lang = "en-US";
  r.interimResults = true;
  r.continuous = false;
  let err: string | undefined;
  r.onresult = (e) => {
    let text = "";
    let final = false;
    for (let i = 0; i < e.results.length; i++) {
      text += e.results[i][0].transcript;
      if (e.results[i].isFinal) final = true;
    }
    onText(text, final);
  };
  r.onerror = (e) => { err = e.error === "no-speech" ? undefined : e.error; };
  r.onend = () => onEnd(err);
  r.start();
  return () => r.stop();
}
