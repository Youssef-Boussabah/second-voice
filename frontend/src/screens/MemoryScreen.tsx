import { useEffect, useState } from "react";
import SensitiveText from "../components/SensitiveText";
import type { Boundary, PersonContext } from "../contracts";
import { api } from "../lib/api";
import { USE_MOCKS } from "../config";
import { mockProposeBoundary } from "../mock/mockBackend";
import ResetDemoButton from "../components/ResetDemoButton";
import { Avatar, relLabel } from "../components/PartnerBar";
import { Button, Chip, IconButton } from "../components/ui";
import Icon from "../components/Icon";
import { listJoin, markAnnounced, scopeLabel, topicLabel, useStore } from "../store";

const STATUS: Record<Boundary["status"], { tone: "voice" | "amber" | "neutral"; label: string }> = {
  active: { tone: "voice", label: "On" },
  proposed: { tone: "amber", label: "Needs your OK" },
  dismissed: { tone: "neutral", label: "Dismissed" },
  retired: { tone: "neutral", label: "Retired" },
};

const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
const fmtDay = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "");

function PersonMemory() {
  const people = useStore((s) => s.people);
  const current = useStore((s) => s.personId);
  const [pid, setPid] = useState<string | null>(current ?? people[0]?.id ?? null);
  const [ctx, setCtx] = useState<PersonContext | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const person = people.find((p) => p.id === pid);

  useEffect(() => {
    if (!pid && people[0]) setPid(people[0].id);
  }, [people, pid]);

  useEffect(() => {
    if (!pid) return;
    setCtx(null);
    setErr(null);
    // a slower response for the previously selected person must not land under this tab
    let alive = true;
    api.personContext(pid)
      .then((c) => alive && setCtx(c))
      .catch((e: unknown) => alive && setErr(e instanceof Error ? e.message : String(e)));
    return () => { alive = false; };
  }, [pid]);

  return (
    <section aria-labelledby="mem-h" className="flex flex-col gap-5">
      <div>
        <h2 id="mem-h" className="flex items-center gap-2.5 text-3xl font-bold tracking-tight"><Icon name="memory" size={28} /> What Second Voice remembers</h2>
        <p className="mt-1 text-lg text-muted">Kept per person in MongoDB Atlas. Anything a privacy rule covers is left out here and never sent to the AI for that person.</p>
      </div>
      <div role="tablist" aria-label="Person" className="flex flex-wrap gap-2">
        {people.map((p) => {
          const on = p.id === pid;
          return (
            <button key={p.id} type="button" role="tab" aria-selected={on} onClick={() => setPid(p.id)}
              className={`flex min-h-16 items-center gap-3 rounded-2xl border py-2 pl-2 pr-4 text-left transition-colors ${on ? "border-ink bg-ink text-white shadow-card" : "border-line bg-surface hover:border-ink/40"}`}>
              <Avatar p={p} size="sm" />
              <span className="leading-tight">
                <span className="block text-lg font-bold">{p.name.split(" ")[0]}</span>
                <span className={`block text-[15px] ${on ? "text-white/80" : "text-muted"}`}>{relLabel(p)}</span>
              </span>
            </button>
          );
        })}
      </div>
      {err && <p role="alert" className="rounded-3xl bg-danger-soft p-4 text-lg text-danger">Couldn't load memory: {err}</p>}
      {!ctx && !err && (
        <div className="grid gap-4 md:grid-cols-2"><div className="skeleton h-36 rounded-4xl md:col-span-2" /><div className="skeleton h-40 rounded-4xl" /><div className="skeleton h-40 rounded-4xl" /></div>
      )}
      {ctx && (
        <div className="grid animate-fadein gap-4 md:grid-cols-2">
          <article className="panel p-5 md:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="eyebrow">Last conversation{ctx.last_episode ? ` · ${fmtDay(ctx.last_episode.created_at)}` : ""}</p>
              <div className="flex flex-wrap gap-1.5">{ctx.last_episode?.topics.map((t) => <Chip key={t}>{topicLabel(t)}</Chip>)}</div>
            </div>
            <p className="mt-2 text-xl leading-relaxed">{ctx.last_episode?.text ?? `Nothing remembered with ${person?.name.split(" ")[0] ?? "them"} yet.`}</p>
          </article>
          <article className="panel p-5">
            <p className="eyebrow">Open threads</p>
            {ctx.open_threads.length ? (
              <ul className="mt-3 flex flex-col gap-2">
                {ctx.open_threads.map((t, i) => (
                  <li key={`${t.id}-${i}`} className="flex items-start gap-2.5 rounded-2xl bg-voice-soft/70 px-3.5 py-2.5 text-lg leading-snug text-voice-dark">
                    <Icon name="reply" size={20} className="mt-0.5" /> {t.text}
                  </li>
                ))}
              </ul>
            ) : <p className="mt-2 text-lg text-muted">Nothing to follow up.</p>}
          </article>
          <article className="panel p-5">
            <p className="eyebrow">Your usual phrases with them</p>
            {ctx.top_phrases.length ? (
              <ul className="mt-3 flex flex-col gap-2 text-lg">
                {ctx.top_phrases.map((p) => <li key={p} className="rounded-2xl border border-line px-3.5 py-2.5 leading-snug">“{p}”</li>)}
              </ul>
            ) : <p className="mt-2 text-lg text-muted">None yet. Phrases you choose are learned automatically.</p>}
          </article>
        </div>
      )}
    </section>
  );
}

function BoundaryList() {
  const boundaries = useStore((s) => s.boundaries);
  const people = useStore((s) => s.people);
  const refresh = useStore((s) => s.refreshBoundaries);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { void refresh(); }, [refresh]);

  const act = async (b: Boundary, confirm: boolean) => {
    setBusy(b._id);
    try {
      const out = confirm ? await api.confirmBoundary(b._id) : await api.dismissBoundary(b._id);
      markAnnounced(out._id);
      useStore.setState((s) => ({
        boundaries: s.boundaries.map((x) => (x._id === out._id ? out : x)),
        privacyLog: [{ id: out._id + Date.now(), at: new Date().toISOString(), kind: confirm ? "confirmed" : "dismissed", boundary: out }, ...s.privacyLog],
      }));
    } catch (e) {
      useStore.getState().pushToast({ tone: "error", title: "Couldn't update rule", body: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  const order: Record<Boundary["status"], number> = { proposed: 0, active: 1, dismissed: 2, retired: 3 };
  const sorted = [...boundaries].sort((a, b) => order[a.status] - order[b.status] || b.created_at.localeCompare(a.created_at));
  const live = sorted.filter((b) => b.status === "proposed" || b.status === "active");
  const past = sorted.filter((b) => b.status === "dismissed" || b.status === "retired");

  const Rule = ({ b }: { b: Boundary }) => (
    <li className={`panel p-5 ${b.status === "proposed" ? "border-amber-line ring-4 ring-amber-soft" : ""} ${past.includes(b) ? "opacity-70 shadow-none" : ""}`}>
      <div className="flex items-start gap-4">
        <span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${b.status === "active" ? "bg-lock-soft text-lock-dark" : "bg-ink/[.05] text-muted"}`}><Icon name="lock" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-xl leading-snug">
            {b.action === "block" ? "Keep" : "Ask before sharing"} <strong>{listJoin(b.topics.map(topicLabel))}</strong> private with <strong>{scopeLabel(b, people)}</strong>
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Chip tone={STATUS[b.status].tone}>{STATUS[b.status].label}</Chip>
            <Chip tone={b.origin === "learned" ? "lock" : "neutral"}>{b.origin === "learned" ? "Learned from you" : b.origin === "seed" ? "Default" : "Manual"}</Chip>
            <span className="text-base text-muted">{fmt(b.activated_at ?? b.created_at)}</span>
          </div>
          {b.evidence.rejected_text && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-lg text-muted">
              <span>Learned from a reply you marked too personal:</span>
              <SensitiveText text={b.evidence.rejected_text} />
            </div>
          )}
          {b.validation.replayed > 0 && (
            <p className="mt-1 flex items-center gap-1.5 text-base text-muted">
              <Icon name="check" size={18} className="text-voice" />
              Checked against {b.validation.replayed} past replies · {b.validation.conflicts} conflict{b.validation.conflicts === 1 ? "" : "s"}
              {b.validation.narrowed_from ? " · narrowed to one person" : ""}
            </p>
          )}
          {b.status === "proposed" && (
            <div className="mt-4 grid grid-cols-2 gap-3">
              <Button disabled={busy === b._id} onClick={() => void act(b, false)}>Dismiss</Button>
              <Button tone="lock" disabled={busy === b._id} onClick={() => void act(b, true)}>Keep private</Button>
            </div>
          )}
        </div>
      </div>
    </li>
  );

  return (
    <section aria-labelledby="bnd-h" className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="bnd-h" className="flex items-center gap-2.5 text-3xl font-bold tracking-tight"><Icon name="shield" size={28} /> Privacy rules</h2>
          <p className="mt-1 text-lg text-muted">Enforced in code before any suggestion is shown. Learned when you mark a reply “too personal”, and checked against what you've actually said first.</p>
        </div>
        <IconButton icon="refresh" label="Refresh privacy rules" onClick={() => void refresh()} />
      </div>
      {USE_MOCKS && (
        <Button tone="ghost" className="self-start text-base" onClick={() => { mockProposeBoundary("service", ["location_schedule"]); void refresh(); }}>
          Mock: simulate a proposed rule
        </Button>
      )}
      {!sorted.length && <p className="panel p-5 text-xl text-muted">No rules yet.</p>}
      <ul className="flex flex-col gap-3">{live.map((b) => <Rule key={b._id} b={b} />)}</ul>
      {past.length > 0 && (
        <details className="group">
          <summary className="flex min-h-16 cursor-pointer list-none items-center gap-2 rounded-2xl px-2 text-lg font-bold text-muted hover:text-ink">
            <Icon name="chevron" size={20} className="transition-transform group-open:rotate-90" /> {past.length} dismissed or retired
          </summary>
          <ul className="mt-2 flex flex-col gap-3">{past.map((b) => <Rule key={b._id} b={b} />)}</ul>
        </details>
      )}
    </section>
  );
}

function PrivacyLog() {
  const log = useStore((s) => s.privacyLog);
  const people = useStore((s) => s.people);
  if (!log.length) return null;
  const verb = { activated: "Learned", proposed: "Proposed", confirmed: "You confirmed", dismissed: "You dismissed" } as const;
  return (
    <section aria-labelledby="log-h" className="panel flex flex-col gap-3 p-5">
      <h2 id="log-h" className="eyebrow">Changes this session</h2>
      <ol className="flex flex-col gap-2">
        {log.map((e) => (
          <li key={e.id} className="flex items-start gap-3 text-lg">
            <span className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-lock" aria-hidden />
            <span><strong>{verb[e.kind]}</strong>: {listJoin(e.boundary.topics.map(topicLabel))} with {scopeLabel(e.boundary, people)} <span className="text-muted">· {fmt(e.at)}</span></span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function MemoryScreen() {
  return (
    <div className="mx-auto grid max-w-[1400px] gap-8 p-5 sm:p-6 xl:grid-cols-2">
      <div className="flex flex-col gap-6"><PersonMemory /><PrivacyLog /><ResetDemoButton className="self-start text-lg" /></div>
      <BoundaryList />
    </div>
  );
}
