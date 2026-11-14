import type { PersonOut } from "../contracts";
import { useStore } from "../store";
import Icon from "./Icon";
import { Button } from "./ui";

const REL_LABEL: Record<PersonOut["relationship"], string> = {
  family: "Family", close_friend: "Close friend", caregiver: "Caregiver", clinician: "Clinician",
  service: "Service", acquaintance: "Acquaintance", stranger: "Stranger",
};

// Relationship → avatar colour, so "how close is this person" reads at a glance.
const REL_TONE: Record<PersonOut["relationship"], string> = {
  family: "bg-clay-soft text-clay-dark", close_friend: "bg-clay-soft text-clay-dark",
  caregiver: "bg-voice-soft text-voice-dark", clinician: "bg-voice-soft text-voice-dark",
  service: "bg-ink/[.06] text-ink", acquaintance: "bg-lock-soft text-lock-dark", stranger: "bg-ink/[.06] text-ink",
};

export const relLabel = (p: PersonOut) => p.label || REL_LABEL[p.relationship];
export const relKind = (p: PersonOut) => REL_LABEL[p.relationship];

export function lastTalked(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return `Last talked ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();

export function Avatar({ p, size = "md" }: { p: PersonOut; size?: "sm" | "md" | "lg" }) {
  const dim = size === "lg" ? "h-16 w-16 text-2xl" : size === "md" ? "h-12 w-12 text-lg" : "h-10 w-10 text-base";
  return <span aria-hidden className={`grid shrink-0 place-items-center rounded-full font-bold ${dim} ${REL_TONE[p.relationship]}`}>{initials(p.name)}</span>;
}

/** "Who are you talking to?" choices. `layout="cards"` for the start screen. */
export function PartnerPicker({ layout = "row" }: { layout?: "row" | "cards" | "compact" }) {
  const people = useStore((s) => s.people);
  const personId = useStore((s) => s.personId);
  const choose = useStore((s) => s.choosePerson);
  const unknown = useStore((s) => s.unknownUtteranceId);
  const assign = useStore((s) => s.assignUnknown);
  const pick = (id: string) => (unknown ? void assign(id) : void choose(id));

  if (layout === "cards") {
    return (
      <div role="radiogroup" aria-label="Who are you talking to?" className="grid gap-4 sm:grid-cols-3">
        {people.map((p, i) => (
          <button key={p.id} type="button" role="radio" aria-checked={p.id === personId} onClick={() => pick(p.id)}
            aria-label={`${p.name}, ${relLabel(p)}`} style={{ animationDelay: `${i * 60}ms` }}
            className="panel group flex animate-fadein flex-col items-start gap-4 p-6 text-left transition-[transform,box-shadow] hover:-translate-y-0.5 hover:shadow-lift">
            <Avatar p={p} size="lg" />
            <span>
              <span className="block text-2xl font-bold">{p.name}</span>
              <span className="mt-1 block text-lg text-muted">{relLabel(p)}</span>
            </span>
            <span className="mt-auto inline-flex items-center gap-1 text-lg font-bold text-clay-dark">
              Start talking <Icon name="chevron" size={20} className="transition-transform group-hover:translate-x-0.5" />
            </span>
          </button>
        ))}
        {!people.length && [0, 1, 2].map((i) => <div key={i} className="skeleton h-56 rounded-4xl" />)}
      </div>
    );
  }

  return (
    <div role="radiogroup" aria-label="Who are you talking to?" className="flex flex-wrap gap-2">
      {people.map((p) => {
        const on = p.id === personId;
        return (
          <button key={p.id} type="button" role="radio" aria-checked={on} onClick={() => pick(p.id)}
            aria-label={`${p.name}, ${relLabel(p)}`}
            className={`flex min-h-16 items-center gap-2.5 rounded-2xl border py-2 pl-2 pr-4 text-left transition-colors ${
              on ? "border-ink bg-ink text-white shadow-card" : "border-line bg-surface hover:border-ink/40"
            }`}>
            <Avatar p={p} size="sm" />
            <span className="text-lg font-bold leading-tight">{p.name.split(" ")[0]}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Who Maya is talking to: name, relationship, last talked, open threads to follow up. */
export function PartnerCard({ compact = false }: { compact?: boolean }) {
  const ctx = useStore((s) => s.context);
  const failed = useStore((s) => s.contextFailed);
  const people = useStore((s) => s.people);
  const personId = useStore((s) => s.personId);
  const session = useStore((s) => s.session);
  const end = useStore((s) => s.endConversation);
  const person = ctx?.person ?? people.find((p) => p.id === personId);
  if (!person) return null;
  const last = lastTalked(ctx?.last_episode?.created_at ?? person.last_seen);
  const seen = new Set<string>();
  const threads = (ctx?.open_threads ?? [])
    .filter((t) => t.status === "open" && !seen.has(t.id) && (seen.add(t.id), true))
    .slice(0, compact ? 2 : 3);

  return (
    <section aria-label="Conversation partner" className="panel flex flex-col gap-4 p-5">
      <div className="flex items-center gap-4">
        <Avatar p={person} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="eyebrow">Talking with</p>
          <h1 className="truncate text-2xl font-bold leading-tight lg:text-[28px]">{person.name}</h1>
          <p className="text-lg text-muted">{relLabel(person)}{last ? ` · ${last}` : ""}</p>
        </div>
        {session && compact && (
          <Button tone="danger" onClick={() => void end()} aria-label="End conversation and save memory">
            <Icon name="power" size={22} /> End
          </Button>
        )}
      </div>
      {failed && <p className="rounded-2xl bg-amber-soft px-3.5 py-2.5 text-lg text-amber">Memory is unavailable right now. Replies still work.</p>}
      {(threads.length > 0 || (!ctx && !failed)) && (
        <div>
          <p className="eyebrow mb-2">Follow up</p>
          {!ctx ? (
            <div className="flex flex-col gap-2"><div className="skeleton h-12 rounded-2xl" /><div className="skeleton h-12 w-3/4 rounded-2xl" /></div>
          ) : (
            <ul className="flex flex-col gap-2">
              {threads.map((t) => (
                <li key={t.id} className="flex items-start gap-2.5 rounded-2xl bg-voice-soft/70 px-3.5 py-2.5 text-lg leading-snug text-voice-dark">
                  <Icon name="reply" size={20} className="mt-0.5" />
                  <span><span className="sr-only">Open thread: </span>{t.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {session && !compact && (
        <Button tone="danger" className="w-full" onClick={() => void end()} aria-label="End conversation and save memory">
          <Icon name="power" size={22} /> End chat
        </Button>
      )}
    </section>
  );
}

// Back-compat name used by older imports.
export const ContextHeader = PartnerCard;
