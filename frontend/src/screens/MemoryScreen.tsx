import { useEffect, useState } from "react";
import type { Boundary, PersonContext } from "../contracts";
import { api } from "../lib/api";
import { USE_MOCKS } from "../config";
import { mockProposeBoundary } from "../mock/mockBackend";
import { relLabel } from "../components/PartnerBar";
import { Button } from "../components/ui";
import { listJoin, scopeLabel, topicLabel, useStore } from "../store";

const STATUS_STYLE: Record<Boundary["status"], string> = {
  active: "bg-sage-soft text-sage",
  proposed: "bg-amber-100 text-amber-800",
  dismissed: "bg-line text-muted",
  retired: "bg-line text-muted",
};

const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "—";

function PersonMemory() {
  const people = useStore((s) => s.people);
  const current = useStore((s) => s.personId);
  const [pid, setPid] = useState<string | null>(current ?? people[0]?.id ?? null);
  const [ctx, setCtx] = useState<PersonContext | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!pid && people[0]) setPid(people[0].id);
  }, [people, pid]);

  useEffect(() => {
    if (!pid) return;
    setCtx(null);
    setErr(null);
    api.personContext(pid).then(setCtx).catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  }, [pid]);

  return (
    <section aria-labelledby="mem-h" className="flex flex-col gap-4 rounded-3xl bg-white/70 p-5">
      <h2 id="mem-h" className="text-2xl font-bold">🧠 What Second Voice remembers</h2>
      <div role="tablist" aria-label="Person" className="flex flex-wrap gap-2">
        {people.map((p) => (
          <button key={p.id} type="button" role="tab" aria-selected={p.id === pid} onClick={() => setPid(p.id)}
            className={`min-h-16 rounded-2xl border-2 px-4 text-lg font-bold ${p.id === pid ? "border-ink bg-ink text-paper" : "border-line bg-white hover:border-clay"}`}>
            {p.name.split(" ")[0]} <span className="font-normal opacity-80">· {relLabel(p)}</span>
          </button>
        ))}
      </div>
      {err && <p className="text-lg text-red-700">Couldn't load memory: {err}</p>}
      {!ctx && !err && <p className="text-lg text-muted">Loading…</p>}
      {ctx && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl bg-white p-4 md:col-span-2">
            <h3 className="text-base font-bold uppercase tracking-wide text-muted">Last conversation · {fmt(ctx.last_episode?.created_at ?? null)}</h3>
            <p className="mt-1 text-xl">{ctx.last_episode?.text ?? "Nothing remembered yet."}</p>
            {ctx.last_episode && ctx.last_episode.topics.length > 0 && (
              <p className="mt-2 flex flex-wrap gap-2">
                {ctx.last_episode.topics.map((t) => (
                  <span key={t} className="rounded-full bg-paper px-3 py-1 text-base text-muted">{topicLabel(t)}</span>
                ))}
              </p>
            )}
          </div>
          <div className="rounded-2xl bg-white p-4">
            <h3 className="text-base font-bold uppercase tracking-wide text-muted">Open threads</h3>
            {ctx.open_threads.length ? (
              <ul className="mt-1 list-disc pl-6 text-xl">
                {ctx.open_threads.map((t) => <li key={t.id}>{t.text} {t.status === "resolved" && <span className="text-muted">(resolved)</span>}</li>)}
              </ul>
            ) : <p className="mt-1 text-xl text-muted">None</p>}
          </div>
          <div className="rounded-2xl bg-white p-4">
            <h3 className="text-base font-bold uppercase tracking-wide text-muted">Your usual phrases with them</h3>
            {ctx.top_phrases.length ? (
              <ul className="mt-1 flex flex-col gap-1 text-xl">{ctx.top_phrases.map((p) => <li key={p}>“{p}”</li>)}</ul>
            ) : <p className="mt-1 text-xl text-muted">None yet</p>}
          </div>
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

  return (
    <section aria-labelledby="bnd-h" className="flex flex-col gap-4 rounded-3xl bg-white/70 p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 id="bnd-h" className="text-2xl font-bold">🔒 Your privacy rules</h2>
        <Button tone="ghost" onClick={() => void refresh()} aria-label="Refresh privacy rules">↻ Refresh</Button>
      </div>
      <p className="text-lg text-muted">Enforced in code before any suggestion is shown. Learned when you mark a reply “too personal”.</p>
      {USE_MOCKS && (
        <Button tone="ghost" className="self-start text-base" onClick={() => mockProposeBoundary("service", ["location_schedule"])}>
          Mock: simulate a proposed rule
        </Button>
      )}
      {sorted.length === 0 && <p className="text-xl text-muted">No rules yet.</p>}
      <ul className="flex flex-col gap-3">
        {sorted.map((b) => (
          <li key={b._id} className={`rounded-2xl bg-white p-4 ${b.status === "dismissed" || b.status === "retired" ? "opacity-60" : ""}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-3 py-1 text-base font-bold ${STATUS_STYLE[b.status]}`}>{b.status}</span>
              <span className="rounded-full bg-paper px-3 py-1 text-base text-muted">{b.origin}</span>
              <span className="text-base text-muted">{fmt(b.activated_at ?? b.created_at)}</span>
            </div>
            <p className="mt-2 text-xl">
              {b.action === "block" ? "Keep" : "Ask before sharing"} <strong>{listJoin(b.topics.map(topicLabel))}</strong> private with <strong>{scopeLabel(b, people)}</strong>
            </p>
            {b.evidence.rejected_text && <p className="text-lg text-muted">Learned from: “{b.evidence.rejected_text}”</p>}
            {b.validation.replayed > 0 && (
              <p className="text-lg text-muted">
                Checked against {b.validation.replayed} past replies · {b.validation.conflicts} conflicts
                {b.validation.narrowed_from ? " · narrowed from a broader rule" : ""}
              </p>
            )}
            {b.status === "proposed" && (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <Button disabled={busy === b._id} onClick={() => void act(b, false)}>Dismiss</Button>
                <Button tone="primary" disabled={busy === b._id} onClick={() => void act(b, true)}>Keep private</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function PrivacyLog() {
  const log = useStore((s) => s.privacyLog);
  const people = useStore((s) => s.people);
  if (!log.length) return null;
  const verb = { activated: "Learned", proposed: "Proposed", confirmed: "You confirmed", dismissed: "You dismissed" } as const;
  return (
    <section aria-labelledby="log-h" className="flex flex-col gap-3 rounded-3xl bg-white/70 p-5">
      <h2 id="log-h" className="text-2xl font-bold">Changes this session</h2>
      <ol className="flex flex-col gap-2">
        {log.map((e) => (
          <li key={e.id} className="rounded-2xl bg-white p-3 text-lg">
            <span className="text-muted">{fmt(e.at)} · </span>
            <strong>{verb[e.kind]}</strong>: {listJoin(e.boundary.topics.map(topicLabel))} with {scopeLabel(e.boundary, people)}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function MemoryScreen() {
  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-4 lg:grid-cols-2">
      <div className="flex flex-col gap-4"><PersonMemory /><PrivacyLog /></div>
      <BoundaryList />
    </div>
  );
}
