import type { PersonOut } from "../contracts";
import { useStore } from "../store";

const REL_LABEL: Record<PersonOut["relationship"], string> = {
  family: "Family", close_friend: "Close friend", caregiver: "Caregiver", clinician: "Clinician",
  service: "Service", acquaintance: "Acquaintance", stranger: "Stranger",
};

export const relLabel = (p: PersonOut) => p.label || REL_LABEL[p.relationship];

export function lastTalked(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return `last talked ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

/** Big "who are you talking to?" chips. */
export function PartnerPicker({ compact = false }: { compact?: boolean }) {
  const people = useStore((s) => s.people);
  const personId = useStore((s) => s.personId);
  const choose = useStore((s) => s.choosePerson);
  const unknown = useStore((s) => s.unknownUtteranceId);
  const assign = useStore((s) => s.assignUnknown);
  const pick = (id: string) => (unknown ? void assign(id) : void choose(id));

  return (
    <div role="radiogroup" aria-label="Who are you talking to?" className={`flex flex-wrap ${compact ? "gap-2" : "gap-3"}`}>
      {people.map((p) => {
        const on = p.id === personId;
        return (
          <button
            key={p.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => pick(p.id)}
            className={`flex min-h-16 items-center gap-3 rounded-2xl border-2 ${compact ? "px-3" : "px-4"} text-left transition-colors ${
              on ? "border-clay bg-clay text-white" : "border-line bg-white hover:border-clay"
            } ${compact ? "py-1" : "py-2"}`}
            aria-label={`${p.name}, ${relLabel(p)}`}
          >
            <span aria-hidden className={`${compact ? "hidden" : "grid"} h-11 w-11 place-items-center rounded-full text-lg font-bold ${on ? "bg-white/25" : "bg-clay-soft text-clay-dark"}`}>
              {initials(p.name)}
            </span>
            <span>
              <span className="block text-xl font-bold leading-tight">{p.name.split(" ")[0]}</span>
              <span className={`block text-base leading-tight ${on ? "text-white/90" : "text-muted"}`}>{relLabel(p)}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** Header: who's talking, relationship, last talked, open-thread chips. */
export function ContextHeader() {
  const ctx = useStore((s) => s.context);
  const people = useStore((s) => s.people);
  const personId = useStore((s) => s.personId);
  const person = ctx?.person ?? people.find((p) => p.id === personId);
  if (!person) return null;
  const last = lastTalked(ctx?.last_episode?.created_at ?? person.last_seen);
  // backend may repeat a thread id across episodes: dedupe, and keep the header to 2 chips
  const seen = new Set<string>();
  const threads = (ctx?.open_threads ?? [])
    .filter((t) => t.status === "open" && !seen.has(t.id) && (seen.add(t.id), true))
    .slice(0, 2);
  return (
    <section aria-label="Conversation partner" className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <h1 className="text-2xl font-bold lg:text-3xl">
        {person.name} <span className="font-normal text-muted">· {relLabel(person)}{last ? ` · ${last}` : ""}</span>
      </h1>
      {threads.map((t) => (
        <span key={t.id} className="rounded-full bg-sage-soft px-4 py-2 text-lg font-bold text-sage">
          <span aria-hidden>🧵 </span>
          <span className="sr-only">Open thread: </span>
          {t.text}
        </span>
      ))}
    </section>
  );
}
