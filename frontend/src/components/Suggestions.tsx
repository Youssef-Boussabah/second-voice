import { useEffect, useRef, useState } from "react";
import type { Candidate, RejectReason } from "../contracts";
import { listJoin, scopeLabel, topicLabel, useStore } from "../store";
import Icon, { type IconName } from "./Icon";
import { Button, IconButton, Sheet } from "./ui";

const LONG_PRESS_MS = 600;

function SourceBadge({ c }: { c: Candidate }) {
  if (c.source === "phrasebook" && c.memory_ids.length) return <Badge icon="history" text="Your phrase" />;
  if (c.source === "phrasebook") return <Badge icon="chat" text="Quick reply" />;
  if (c.memory_ids.length) return <Badge icon="memory" text={`From ${c.memory_ids.length === 1 ? "a memory" : `${c.memory_ids.length} memories`}`} tone="voice" />;
  return <Badge icon="sparkle" text="Suggested" />;
}

function Badge({ icon, text, tone = "neutral" }: { icon: IconName; text: string; tone?: "neutral" | "voice" }) {
  return (
    <span className={`inline-flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[15px] font-bold ${tone === "voice" ? "bg-voice-soft text-voice-dark" : "bg-ink/[.05] text-muted"}`}>
      <Icon name={icon} size={16} /> <span className="truncate">{text}</span>
    </span>
  );
}

function Bars() {
  return (
    <span aria-hidden className="flex h-5 items-center gap-[3px]">
      {[0, 1, 2, 3].map((i) => <span key={i} className="h-full w-[3px] origin-center animate-bar rounded-full bg-voice" style={{ animationDelay: `${i * 0.12}s` }} />)}
    </span>
  );
}

function SuggestionCard({ c, index, onMore, onEdit }: { c: Candidate; index: number; onMore: () => void; onEdit: () => void }) {
  const speakingId = useStore((s) => s.speakingId);
  const chosenId = useStore((s) => s.suggestions?.chosen_candidate_id);
  const speakCandidate = useStore((s) => s.speakCandidate);
  const stop = useStore((s) => s.stopSpeech);
  const timer = useRef<number>();
  const longPressed = useRef(false);

  const speaking = speakingId === c.id;
  const otherSpeaking = !!speakingId && !speaking;
  const chosen = chosenId === c.id && !speaking;

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
    <div style={{ animationDelay: `${index * 45}ms` }}
      className={`group relative flex min-h-[156px] animate-fadein flex-col rounded-4xl border-2 transition-[border-color,background-color,box-shadow,opacity] duration-200 ${
        speaking ? "animate-speak border-voice bg-voice-soft/60 shadow-lift"
          : chosen ? "border-voice/50 bg-surface shadow-card"
            : "border-transparent bg-surface shadow-card hover:border-ink/15 hover:shadow-lift"
      } ${otherSpeaking ? "opacity-45" : ""}`}>
      {/* The ONLY path to speech: an explicit tap on this button. Tapping again stops. */}
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
          if (speaking) return stop();
          void speakCandidate(c);
        }}
        aria-label={speaking ? `Stop speaking: ${c.text}` : `Say: ${c.text}`}
        aria-describedby={`cand-hint-${c.id}`}
        aria-keyshortcuts={String(index + 1)}
        className="flex flex-1 select-none items-start gap-3.5 rounded-t-4xl px-5 pb-2 pt-5 text-left"
      >
        <span aria-hidden className={`mt-1 grid h-9 w-9 shrink-0 place-items-center rounded-xl text-lg font-bold ${speaking ? "bg-voice text-white" : "bg-ink/[.06] text-muted"}`}>
          {index + 1}
        </span>
        <span className="text-[27px] font-bold leading-[1.22] tracking-[-0.005em] text-ink lg:text-[29px]">{c.text}</span>
      </button>
      <span id={`cand-hint-${c.id}`} className="sr-only">Tap to speak. Long-press or use More to reject.</span>
      <div className="flex min-w-0 items-center gap-1 pb-2 pl-5 pr-2">
        <span role="status" className="flex min-w-0 flex-1 items-center gap-2">
          {speaking ? (
            <span className="inline-flex items-center gap-2 text-base font-bold text-voice-dark"><Bars /> Speaking · tap to stop</span>
          ) : chosen ? (
            <span className="inline-flex items-center gap-1.5 text-base font-bold text-voice-dark"><Icon name="check" size={18} /> Said</span>
          ) : (
            <SourceBadge c={c} />
          )}
        </span>
        <IconButton icon="pencil" label={`Edit before speaking: ${c.text}`} onClick={onEdit} disabled={!!speakingId} />
        <IconButton icon="more" label={`More options for: ${c.text}`} onClick={onMore} disabled={!!speakingId} />
      </div>
    </div>
  );
}

const REASONS: { id: RejectReason; label: string; hint: string; icon: IconName }[] = [
  { id: "too_personal", label: "Too personal for them", hint: "Learn to keep this kind of topic private with this relationship", icon: "lock" },
  { id: "not_my_style", label: "Not how I talk", hint: "Hide it and suggest it less", icon: "chat" },
  { id: "wrong_facts", label: "Wrong facts", hint: "Hide it", icon: "alert" },
];

function RejectSheet({ c, onClose }: { c: Candidate; onClose: () => void }) {
  const reject = useStore((s) => s.rejectCandidate);
  const person = useStore((s) => s.people.find((p) => p.id === s.personId));
  return (
    <Sheet title="What's wrong with this reply?" onClose={onClose} labelledBy="reject-title" icon="more">
      <blockquote className="mb-5 rounded-3xl border border-line bg-surface p-5 text-2xl font-bold leading-snug">“{c.text}”</blockquote>
      <div className="flex flex-col gap-3">
        {REASONS.map((r) => (
          <button key={r.id} type="button" onClick={() => { onClose(); void reject(c, r.id); }}
            className={`flex min-h-20 items-center gap-4 rounded-3xl px-5 py-3 text-left transition-colors ${
              r.id === "too_personal" ? "bg-lock text-white shadow-card hover:bg-lock-dark" : "border border-line bg-surface hover:border-ink/30"}`}>
            <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${r.id === "too_personal" ? "bg-white/15" : "bg-ink/[.05]"}`}><Icon name={r.icon} /></span>
            <span>
              <span className="block text-2xl font-bold">{r.id === "too_personal" && person ? `Too personal for ${person.name.split(" ")[0]}` : r.label}</span>
              <span className={`block text-lg ${r.id === "too_personal" ? "text-white/85" : "text-muted"}`}>{r.hint}</span>
            </span>
          </button>
        ))}
      </div>
    </Sheet>
  );
}

function SpeakTextSheet({ title, initial, onSpeak, onClose }: { title: string; initial: string; onSpeak: (t: string) => void; onClose: () => void }) {
  const [text, setText] = useState(initial);
  return (
    <Sheet title={title} onClose={onClose} labelledBy="speak-title" icon={initial ? "pencil" : "keyboard"}>
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onClose(); onSpeak(text); } }} className="flex flex-col gap-4">
        <label htmlFor="speak-text" className="sr-only">{title}</label>
        <textarea id="speak-text" value={text} maxLength={1000} onChange={(e) => setText(e.target.value)} rows={3}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (text.trim()) { onClose(); onSpeak(text); } } }}
          className="w-full resize-none rounded-3xl border border-line bg-surface p-5 text-2xl leading-snug shadow-card focus:border-ink/50 focus:outline-none" />
        <div className="grid grid-cols-2 gap-3">
          <Button tone="secondary" onClick={onClose}>Cancel</Button>
          <Button tone="voice" type="submit" disabled={!text.trim()} className="text-2xl"><Icon name="speaker" /> Speak</Button>
        </div>
      </form>
    </Sheet>
  );
}

/** "N hidden by your privacy rules" → read-only list of which rule hid what. */
function HiddenNotice() {
  const blocked = useStore((s) => s.suggestions?.blocked ?? []);
  const boundaries = useStore((s) => s.boundaries);
  const people = useStore((s) => s.people);
  const [open, setOpen] = useState(false);
  if (!blocked.length) return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        aria-label={`${blocked.length} ${blocked.length === 1 ? "suggestion" : "suggestions"} hidden by your privacy rules. Show which.`}
        className="inline-flex min-h-16 animate-fadein items-center gap-2.5 rounded-2xl bg-lock-soft px-5 text-xl font-bold text-lock-dark transition-colors hover:bg-lock/15">
        <Icon name="lock" /> {blocked.length} hidden by your privacy rules
      </button>
      {open && (
        <Sheet title="Hidden by your privacy rules" onClose={() => setOpen(false)} labelledBy="hidden-title" icon="lock">
          <p className="mb-4 text-lg text-muted">These were never shown. The rule is enforced in code, before anything reaches the screen.</p>
          <ul className="flex flex-col gap-3">
            {blocked.map((c) => {
              const b = boundaries.find((x) => x._id === c.blocked_by);
              return (
                <li key={c.id} className="rounded-3xl border border-line bg-surface p-4">
                  <p className="text-xl text-muted line-through decoration-lock/50">“{c.text}”</p>
                  <p className="mt-1 flex items-center gap-2 text-lg font-bold text-lock-dark">
                    <Icon name="shield" size={20} />
                    {b ? `Keep ${listJoin(b.topics.map(topicLabel))} private with ${scopeLabel(b, people)}` : "Privacy rule"}
                  </p>
                </li>
              );
            })}
          </ul>
        </Sheet>
      )}
    </>
  );
}

function StageIndicator() {
  const set_ = useStore((s) => s.suggestions);
  const busy = useStore((s) => s.busy);
  const person = useStore((s) => s.people.find((p) => p.id === s.personId));
  const first = person?.name.split(" ")[0] ?? "them";
  if (!set_) {
    return busy ? <span className="text-base font-bold text-muted">Listening…</span> : null;
  }
  if (set_.stage === "instant") {
    return (
      <span role="status" className="inline-flex items-center gap-2 rounded-full bg-amber-soft px-3.5 py-1.5 text-base font-bold text-amber">
        <span aria-hidden className="flex gap-1">{[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 animate-dot rounded-full bg-amber" style={{ animationDelay: `${i * 0.18}s` }} />)}</span>
        Personalizing for {first}…
      </span>
    );
  }
  const ms = set_.latency_ms.since_utterance ?? set_.latency_ms.total;
  return (
    <span role="status" className="inline-flex items-center gap-2 rounded-full bg-voice-soft px-3.5 py-1.5 text-base font-bold text-voice-dark">
      <Icon name="sparkle" size={18} /> Personalized for {first}{ms ? <span className="font-normal opacity-80">· {(ms / 1000).toFixed(1)} s</span> : null}
    </span>
  );
}

export default function Suggestions() {
  const set_ = useStore((s) => s.suggestions);
  const speakCandidate = useStore((s) => s.speakCandidate);
  const speakTyped = useStore((s) => s.speakTyped);
  const stop = useStore((s) => s.stopSpeech);
  const speakingId = useStore((s) => s.speakingId);
  const busy = useStore((s) => s.busy);
  const person = useStore((s) => s.people.find((p) => p.id === s.personId));
  const [rejecting, setRejecting] = useState<Candidate | null>(null);
  const [editing, setEditing] = useState<Candidate | null>(null);
  const [typing, setTyping] = useState(false);

  const cands = set_?.candidates.slice(0, 4) ?? [];
  const sheetOpen = !!(rejecting || editing || typing);

  // Keyboard / switch access: 1-4 speaks a card, Escape stops speech. Ignored while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (sheetOpen || e.altKey || e.ctrlKey || e.metaKey || el?.closest("textarea, input, [role=dialog]")) return;
      if (e.key === "Escape" && speakingId) return stop();
      const n = Number(e.key);
      if (n >= 1 && n <= cands.length && !speakingId) {
        e.preventDefault();
        void speakCandidate(cands[n - 1]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cands, speakingId, sheetOpen, speakCandidate, stop]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex min-h-10 flex-wrap items-center justify-between gap-2">
        <h2 className="text-2xl font-bold tracking-tight">Tap a reply to say it</h2>
        <StageIndicator />
      </div>

      {cands.length > 0 ? (
        <div key={`${set_?._id}-${set_?.stage}`} className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {cands.map((c, i) => (
            <SuggestionCard key={c.id} c={c} index={i} onMore={() => setRejecting(c)} onEdit={() => setEditing(c)} />
          ))}
        </div>
      ) : busy ? (
        <div aria-label="Finding replies" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-[156px] rounded-4xl" />)}
        </div>
      ) : (
        <div className="flex min-h-[240px] flex-col items-center justify-center gap-3 rounded-4xl border-2 border-dashed border-line-strong/80 bg-surface/40 p-8 text-center">
          <span className="grid h-16 w-16 place-items-center rounded-3xl bg-surface text-muted shadow-card"><Icon name="chat" size={30} /></span>
          <p className="text-2xl font-bold">{set_ ? "No more suggestions" : `Replies appear when ${person?.name.split(" ")[0] ?? "they"} speaks`}</p>
          <p className="max-w-md text-lg text-muted">{set_ ? "Type your own reply below." : "Type what they said, or use a Try line. Nothing is ever spoken without your tap."}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <HiddenNotice />
        <Button tone="secondary" className="ml-auto" disabled={!!speakingId} onClick={() => setTyping(true)}>
          <Icon name="keyboard" /> Type my own
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
