import { useEffect, useRef, useState } from "react";
import { dictationSupported, startDictation } from "../lib/dictation";
import { useStore } from "../store";
import Icon from "./Icon";
import { PartnerPicker } from "./PartnerBar";

const DEMO_LINES: Record<string, string[]> = {
  per_dana: ["Hi Maya! Here for your refill?", "Any side effects with the new generic?"],
  per_mike: ["Hey Maya! How've you been?", "Anything new?"],
  per_sam: ["Hi Grandma! We won on Saturday!", "Anything new?"],
};

const MAX_LEN = 600;

/** "What did they say?" Typed or dictated partner speech → POST /api/utterances/text.
 *  Dictation uses the BROWSER's speech recognition (Web Speech API) to fill the box; nothing is
 *  sent until the user taps Send. */
export function IncomingInput() {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const stopRef = useRef<() => void>();
  const busy = useStore((s) => s.busy);
  const personId = useStore((s) => s.personId);
  const people = useStore((s) => s.people);
  const send = useStore((s) => s.sendIncoming);
  const toast = useStore((s) => s.pushToast);
  const first = people.find((p) => p.id === personId)?.name.split(" ")[0] ?? "they";

  useEffect(() => () => stopRef.current?.(), []);

  const submit = async (t = text) => {
    if (!t.trim() || busy) return;
    stopRef.current?.();
    setText("");
    if (!(await send(t.slice(0, MAX_LEN)))) setText(t); // keep their words if sending failed
  };

  const toggleMic = () => {
    if (listening) {
      stopRef.current?.();
      return;
    }
    setListening(true);
    stopRef.current = startDictation(
      (t) => setText(t),
      (err) => {
        setListening(false);
        if (err) toast({ tone: "error", title: "Couldn't hear that", body: err === "not-allowed" ? "Microphone permission was denied. You can still type what they said." : err });
      },
    );
  };

  const demo = personId ? DEMO_LINES[personId] ?? [] : [];

  return (
    <form aria-label="What did they say?" className="flex flex-col gap-3"
      onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <label htmlFor="incoming" className="eyebrow">What did {first} say?</label>
      <div className={`flex items-end gap-2 rounded-3xl border bg-surface p-2 shadow-card transition-colors focus-within:border-ink/50 ${listening ? "border-voice" : "border-line"}`}>
        <textarea
          id="incoming"
          value={text}
          maxLength={MAX_LEN}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={2}
          placeholder={listening ? "Listening…" : dictationSupported ? "Type it, or tap the mic" : "Type what they said"}
          className="min-h-16 flex-1 resize-none bg-transparent px-3 py-2.5 text-xl leading-snug placeholder:text-muted/70 focus:outline-none"
        />
        {dictationSupported && (
          <button type="button" onClick={toggleMic} aria-pressed={listening}
            aria-label={listening ? "Stop listening" : "Listen with browser speech recognition"}
            title="Browser speech recognition fills the box; nothing is sent until you tap Send"
            className={`grid h-16 w-16 shrink-0 place-items-center rounded-2xl transition-colors ${listening ? "animate-speak bg-voice text-white" : "bg-ink/[.05] text-ink hover:bg-ink/10"}`}>
            <Icon name={listening ? "stop" : "mic"} size={26} />
          </button>
        )}
        <button type="submit" disabled={!text.trim() || busy} aria-label="Send and get replies"
          className="grid h-16 w-16 shrink-0 place-items-center rounded-2xl bg-ink text-white shadow-card transition-colors hover:bg-ink-soft disabled:bg-line disabled:text-muted disabled:shadow-none">
          {busy ? <span className="h-6 w-6 animate-spin rounded-full border-[3px] border-white/40 border-t-white" /> : <Icon name="send" size={26} />}
        </button>
      </div>
      <div role="status" aria-live="polite" className="sr-only">{listening ? "Listening" : ""}</div>
      {demo.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Demo lines">
          <span className="text-base font-bold text-muted">Try:</span>
          {demo.map((d) => (
            <button key={d} type="button" onClick={() => void submit(d)} disabled={busy}
              className="min-h-12 rounded-full border border-dashed border-line-strong bg-surface/60 px-4 text-base text-muted transition-colors hover:border-ink/40 hover:text-ink disabled:opacity-50">
              “{d}”
            </button>
          ))}
        </div>
      )}
    </form>
  );
}

/** Recent turns: partner left, Maya right. */
export function Transcript({ max = 6 }: { max?: number }) {
  const turns = useStore((s) => s.turns);
  const people = useStore((s) => s.people);
  const last = turns.slice(-max);
  const endRef = useRef<HTMLLIElement>(null);
  useEffect(() => {
    const li = endRef.current;
    const box = li?.closest("[data-scrollbox]");
    if (box) box.scrollTop = box.scrollHeight;
  }, [turns.length]);
  if (!last.length) {
    return (
      <div className="flex h-full min-h-24 flex-col items-center justify-center gap-2 px-4 py-6 text-center text-muted">
        <Icon name="chat" size={28} className="opacity-60" />
        <p className="text-lg">The conversation will appear here.</p>
      </div>
    );
  }
  return (
    <ol aria-label="Recent conversation" aria-live="polite" className="flex flex-col gap-2.5">
      {last.map((u, i) => {
        const mine = u.speaker.kind === "user";
        const who = mine ? "You" : people.find((p) => p.id === u.speaker.person_id)?.name.split(" ")[0] ?? "Them";
        return (
          <li key={u._id} ref={i === last.length - 1 ? endRef : undefined} className={`flex animate-fadein ${mine ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[88%] rounded-3xl px-4 py-2.5 text-lg leading-snug ${mine ? "rounded-br-lg bg-ink text-white" : "rounded-bl-lg border border-line bg-surface text-ink"}`}>
              <span className={`block text-sm font-bold uppercase tracking-wide ${mine ? "text-white/70" : "text-muted"}`}>{who}</span>
              {u.text}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Shown when the backend can't tell who spoke. Never guesses silently. */
export function WhosThis() {
  const unknown = useStore((s) => s.unknownUtteranceId);
  if (!unknown) return null;
  return (
    <div role="alert" className="flex animate-fadein flex-col gap-3 rounded-4xl border border-amber-line bg-amber-soft p-5">
      <p className="flex items-center gap-2 text-2xl font-bold text-ink"><Icon name="user" /> Who's this?</p>
      <p className="text-lg text-muted">I couldn't tell who spoke. Pick them so replies fit.</p>
      <PartnerPicker />
    </div>
  );
}
