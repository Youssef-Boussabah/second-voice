import { useRef, useState } from "react";
import type { Candidate, RejectReason } from "../contracts";
import { listJoin, scopeLabel, topicLabel, useStore } from "../store";
import { Button, Sheet } from "./ui";

const LONG_PRESS_MS = 600;

function SuggestionCard({ c, index, onMore, onEdit }: { c: Candidate; index: number; onMore: () => void; onEdit: () => void }) {
  const speakingId = useStore((s) => s.speakingId);
  const chosenId = useStore((s) => s.suggestions?.chosen_candidate_id);
  const speakCandidate = useStore((s) => s.speakCandidate);
  const timer = useRef<number>();
  const longPressed = useRef(false);

  const speaking = speakingId === c.id;
  const otherSpeaking = !!speakingId && !speaking;

  const startPress = () => {
    longPressed.current = false;
    timer.current = window.setTimeout(() => {
      longPressed.current = true;
      if (navigator.vibrate) navigator.vibrate(30);
      onMore();
    }, LONG_PRESS_MS);
  };
  const cancelPress = () => window.clearTimeout(timer.current);

  return (
    <div
      className={`flex min-h-36 flex-col rounded-3xl border-4 bg-white shadow-sm transition-colors ${
        speaking ? "animate-speak border-sage" : chosenId === c.id ? "border-sage/60" : "border-line hover:border-clay"
      } ${otherSpeaking ? "opacity-50" : ""}`}
    >
      {/* The ONLY path to speech: an explicit tap on this button. */}
      <button
        type="button"
        disabled={otherSpeaking}
        onPointerDown={startPress}
        onPointerUp={cancelPress}
        onPointerLeave={cancelPress}
        onPointerCancel={cancelPress}
        onContextMenu={(e) => e.preventDefault()}
        onClick={() => {
          if (longPressed.current) return;
          void speakCandidate(c);
        }}
        aria-label={`Say: ${c.text}`}
        aria-describedby={`cand-hint-${c.id}`}
        className="flex flex-1 select-none items-start rounded-t-3xl px-5 pb-2 pt-4 text-left text-[28px] font-bold leading-tight"
      >
        <span aria-hidden className="mr-3 mt-1 text-lg font-bold text-muted">{index + 1}</span>
        <span>{c.text}</span>
      </button>
      <span id={`cand-hint-${c.id}`} className="sr-only">
        Tap to speak. Long-press or use More to reject.
      </span>
      <div className="flex items-center gap-2 px-3 pb-2">
        <span role="status" className="flex-1 pl-2 text-base font-bold text-sage">{speaking ? "🔊 Speaking…" : ""}</span>
        <button type="button" onClick={onEdit} disabled={!!speakingId} aria-label={`Edit before speaking: ${c.text}`}
          className="grid h-16 w-16 place-items-center rounded-2xl text-2xl hover:bg-clay-soft">
          <span aria-hidden>✏️</span>
        </button>
        <button type="button" onClick={onMore} disabled={!!speakingId} aria-label={`More options for: ${c.text}`}
          className="grid h-16 w-16 place-items-center rounded-2xl text-3xl font-bold hover:bg-clay-soft">
          <span aria-hidden>⋯</span>
        </button>
      </div>
    </div>
  );
}

const REASONS: { id: RejectReason; label: string; hint: string }[] = [
  { id: "too_personal", label: "🔒 Too personal", hint: "Learn to keep this kind of thing private with them" },
  { id: "not_my_style", label: "Not how I talk", hint: "Hide it" },
  { id: "wrong_facts", label: "Wrong facts", hint: "Hide it" },
];

function RejectSheet({ c, onClose }: { c: Candidate; onClose: () => void }) {
  const reject = useStore((s) => s.rejectCandidate);
  return (
    <Sheet title="What's wrong with this reply?" onClose={onClose} labelledBy="reject-title">
      <p className="mb-4 rounded-2xl bg-white p-4 text-2xl">“{c.text}”</p>
      <div className="flex flex-col gap-3">
        {REASONS.map((r) => (
          <Button key={r.id} tone={r.id === "too_personal" ? "primary" : "secondary"} className="min-h-20 text-left text-2xl"
            onClick={() => { onClose(); void reject(c, r.id); }}>
            {r.label}
            <span className="block text-base font-normal opacity-80">{r.hint}</span>
          </Button>
        ))}
        <Button tone="ghost" onClick={onClose}>Cancel</Button>
      </div>
    </Sheet>
  );
}

function SpeakTextSheet({ title, initial, onSpeak, onClose }: { title: string; initial: string; onSpeak: (t: string) => void; onClose: () => void }) {
  const [text, setText] = useState(initial);
  return (
    <Sheet title={title} onClose={onClose} labelledBy="speak-title">
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onClose(); onSpeak(text); } }} className="flex flex-col gap-4">
        <label htmlFor="speak-text" className="sr-only">{title}</label>
        <textarea id="speak-text" value={text} onChange={(e) => setText(e.target.value)} rows={3}
          className="w-full resize-none rounded-2xl border-2 border-line bg-white p-4 text-2xl focus:border-clay focus:outline-none" />
        <div className="grid grid-cols-2 gap-3">
          <Button tone="ghost" onClick={onClose}>Cancel</Button>
          <Button tone="sage" type="submit" disabled={!text.trim()} className="text-2xl">🔊 Speak</Button>
        </div>
      </form>
    </Sheet>
  );
}

/** "🔒 N hidden by your boundaries" → read-only list of which rule hid what. */
function HiddenNotice() {
  const blocked = useStore((s) => s.suggestions?.blocked ?? []);
  const boundaries = useStore((s) => s.boundaries);
  const people = useStore((s) => s.people);
  const [open, setOpen] = useState(false);
  if (!blocked.length) return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        aria-label={`${blocked.length} ${blocked.length === 1 ? "suggestion" : "suggestions"} hidden by your boundaries. Show which.`}
        className="min-h-16 self-start rounded-2xl bg-lock-soft px-5 text-xl font-bold text-lock hover:brightness-95">
        🔒 {blocked.length} hidden by your boundaries
      </button>
      {open && (
        <Sheet title="Hidden by your boundaries" onClose={() => setOpen(false)} labelledBy="hidden-title">
          <ul className="flex flex-col gap-3">
            {blocked.map((c) => {
              const b = boundaries.find((x) => x._id === c.blocked_by);
              return (
                <li key={c.id} className="rounded-2xl bg-white p-4">
                  <p className="text-xl line-through decoration-lock/60">“{c.text}”</p>
                  <p className="text-lg text-lock">
                    {b ? `Rule: keep ${listJoin(b.topics.map(topicLabel))} private with ${scopeLabel(b, people)}` : `Rule ${c.blocked_by ?? "unknown"}`}
                  </p>
                </li>
              );
            })}
          </ul>
          <Button className="mt-4 w-full" onClick={() => setOpen(false)}>Close</Button>
        </Sheet>
      )}
    </>
  );
}

export default function Suggestions() {
  const set_ = useStore((s) => s.suggestions);
  const speakCandidate = useStore((s) => s.speakCandidate);
  const speakTyped = useStore((s) => s.speakTyped);
  const speakingId = useStore((s) => s.speakingId);
  const busy = useStore((s) => s.busy);
  const [rejecting, setRejecting] = useState<Candidate | null>(null);
  const [editing, setEditing] = useState<Candidate | null>(null);
  const [typing, setTyping] = useState(false);

  const cands = set_?.candidates.slice(0, 4) ?? [];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex min-h-7 items-center justify-between">
        <h2 className="text-lg font-bold text-muted">Tap a reply to say it</h2>
        {set_?.stage === "instant" && <span role="status" className="text-base text-muted">Refining…</span>}
      </div>

      {cands.length > 0 ? (
        <div key={`${set_?._id}-${set_?.stage}`} className="grid animate-fadein grid-cols-2 gap-3">
          {cands.map((c, i) => (
            <SuggestionCard key={c.id} c={c} index={i} onMore={() => setRejecting(c)} onEdit={() => setEditing(c)} />
          ))}
        </div>
      ) : (
        <div className="grid min-h-40 place-items-center rounded-3xl border-4 border-dashed border-line p-6 text-center text-2xl text-muted">
          {busy ? "Finding replies…" : set_ ? "No more suggestions. Type your own below." : "Replies appear here after they speak."}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <HiddenNotice />
        <Button tone="secondary" className="ml-auto" disabled={!!speakingId} onClick={() => setTyping(true)}>
          ⌨️ Type my own
        </Button>
      </div>

      {rejecting && <RejectSheet c={rejecting} onClose={() => setRejecting(null)} />}
      {editing && (
        <SpeakTextSheet title="Edit, then speak" initial={editing.text}
          onSpeak={(t) => void speakCandidate(editing, t)} onClose={() => setEditing(null)} />
      )}
      {typing && <SpeakTextSheet title="Type my own" initial="" onSpeak={(t) => void speakTyped(t)} onClose={() => setTyping(false)} />}
    </div>
  );
}
