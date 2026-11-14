import { useEffect, useRef, useState } from "react";
import { dictationSupported, startDictation } from "../lib/dictation";
import { useStore } from "../store";
import { Button } from "./ui";
import { PartnerPicker } from "./PartnerBar";

const DEMO_LINES: Record<string, string[]> = {
  per_dana: ["Hi Maya! Here for your refill?", "Any side effects with the new generic?"],
  per_mike: ["Hey Maya! How've you been?", "Anything new?"],
  per_sam: ["Hey you! How are you doing?", "Anything new?"],
};

/** "What did they say?" Typed or dictated partner speech → POST /api/utterances/text. */
export function IncomingInput() {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const stopRef = useRef<() => void>();
  const busy = useStore((s) => s.busy);
  const personId = useStore((s) => s.personId);
  const send = useStore((s) => s.sendIncoming);
  const toast = useStore((s) => s.pushToast);

  useEffect(() => () => stopRef.current?.(), []);

  const submit = async (t = text) => {
    if (!t.trim() || busy) return;
    stopRef.current?.();
    await send(t);
    setText("");
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
        if (err) toast({ tone: "error", title: "Couldn't hear that", body: err });
      },
    );
  };

  const demo = personId ? DEMO_LINES[personId] ?? [] : [];

  return (
    <form
      aria-label="What did they say?"
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label htmlFor="incoming" className="text-lg font-bold text-muted">What did they say?</label>
      <div className="flex gap-3">
        <textarea
          id="incoming"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={2}
          placeholder={listening ? "Listening…" : "Type or tap the mic"}
          className="min-h-16 flex-1 resize-none rounded-2xl border-2 border-line bg-white p-3 text-xl focus:border-clay focus:outline-none"
        />
        {dictationSupported && (
          <button
            type="button"
            onClick={toggleMic}
            aria-pressed={listening}
            aria-label={listening ? "Stop listening" : "Listen to what they say"}
            className={`min-h-16 min-w-16 rounded-2xl border-2 text-3xl ${listening ? "animate-speak border-sage bg-sage text-white" : "border-line bg-white hover:border-clay"}`}
          >
            <span aria-hidden>{listening ? "■" : "🎤"}</span>
          </button>
        )}
      </div>
      <div role="status" aria-live="polite" className="sr-only">{listening ? "Listening" : ""}</div>
      <Button tone="primary" type="submit" disabled={!text.trim() || busy}>
        {busy ? "Thinking…" : "Get replies"}
      </Button>
      {demo.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Demo lines">
          {demo.map((d) => (
            <button key={d} type="button" onClick={() => void submit(d)} disabled={busy}
              className="min-h-12 rounded-xl border-2 border-dashed border-line px-3 text-base text-muted hover:border-clay hover:text-ink">
              “{d}”
            </button>
          ))}
        </div>
      )}
    </form>
  );
}

/** Last 4 turns: partner left, Maya right. */
export function Transcript() {
  const turns = useStore((s) => s.turns);
  const people = useStore((s) => s.people);
  const last = turns.slice(-4);
  const endRef = useRef<HTMLLIElement>(null);
  useEffect(() => {
    // scroll only the transcript's own scroll container, never the page
    const li = endRef.current;
    const box = li?.closest("[data-scrollbox]");
    if (box) box.scrollTop = box.scrollHeight;
  }, [turns.length]);
  if (!last.length) return <p className="text-lg text-muted">No conversation yet.</p>;
  return (
    <ol aria-label="Recent conversation" aria-live="polite" className="flex flex-col gap-2">
      {last.map((u, i) => {
        const mine = u.speaker.kind === "user";
        const who = mine ? "You" : people.find((p) => p.id === u.speaker.person_id)?.name.split(" ")[0] ?? "Them";
        return (
          <li key={u._id} ref={i === last.length - 1 ? endRef : undefined} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-2 text-xl ${mine ? "bg-clay-soft text-ink" : "bg-white text-ink"} border-2 border-line`}>
              <span className="block text-sm font-bold uppercase tracking-wide text-muted">{who}</span>
              {u.text}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** Shown when the backend can't tell who spoke. */
export function WhosThis() {
  const unknown = useStore((s) => s.unknownUtteranceId);
  if (!unknown) return null;
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-2xl border-2 border-amber-500 bg-amber-50 p-4">
      <p className="text-2xl font-bold">Who's this?</p>
      <PartnerPicker />
    </div>
  );
}
