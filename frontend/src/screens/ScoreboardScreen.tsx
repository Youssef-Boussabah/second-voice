import { useCallback, useEffect, useState } from "react";
import type { ConfigMetrics, Scoreboard } from "../contracts";
import { api } from "../lib/api";
import { IconButton } from "../components/ui";
import Icon from "../components/Icon";

type Key = keyof ConfigMetrics;
const ROWS: { key: Key; label: string; better: "up" | "down"; fmt: (v: number) => string }[] = [
  { key: "hit_at_4", label: "Hit@4 (right reply in top 4)", better: "up", fmt: (v) => `${Math.round(v * 100)}%` },
  { key: "taps_per_message", label: "Taps per message", better: "down", fmt: (v) => v.toFixed(1) },
  { key: "leaks_per_conversation", label: "Privacy leaks / conversation", better: "down", fmt: (v) => v.toFixed(2) },
  { key: "latency_p50_ms", label: "Latency p50", better: "down", fmt: (v) => `${(v / 1000).toFixed(2)} s` },
  { key: "latency_p95_ms", label: "Latency p95", better: "down", fmt: (v) => `${(v / 1000).toFixed(2)} s` },
  { key: "rules_learned", label: "Rules learned", better: "up", fmt: (v) => String(v) },
  { key: "false_positive_rules", label: "False-positive rules", better: "down", fmt: (v) => String(v) },
];

export default function ScoreboardScreen() {
  const [sb, setSb] = useState<Scoreboard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    setErr(null);
    api.scoreboard().then(setSb).catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);
  // Honesty: synthetic runs must never read as real AI measurements.
  const mock = !!sb && /^MOCK/i.test(sb.notes);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-5 p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2.5 text-3xl font-bold tracking-tight"><Icon name="chart" size={28} /> Cold vs warm memory</h1>
          <p className="mt-1 text-lg text-muted">The same scripted conversations replayed with memory off (cold) and on (warm).</p>
        </div>
        <IconButton icon="refresh" label="Refresh evaluation" onClick={load} />
      </div>
      {mock && (
        <div role="note" className="flex items-start gap-4 rounded-4xl border border-amber-line bg-amber-soft p-5">
          <Icon name="alert" size={28} className="mt-0.5 text-amber" />
          <div>
            <p className="text-xl font-bold">MOCK run: not a real AI measurement</p>
            <p className="mt-1 text-lg text-ink/80">These numbers come from the test harness with a canned LLM and random (non-semantic) embeddings. They only show the evaluation pipeline works. No real cold-vs-warm result has been recorded yet.</p>
          </div>
        </div>
      )}
      {err && <p role="alert" className="rounded-3xl bg-danger-soft p-4 text-xl text-danger">Evaluation unavailable: {err}</p>}
      {!sb && !err && <div className="skeleton h-80 rounded-4xl" />}
      {sb && (!sb.cold || !sb.warm) && <p className="panel p-5 text-xl text-muted">No evaluation runs yet.</p>}
      {sb?.cold && sb.warm && (
        <div className={`panel overflow-hidden ${mock ? "opacity-75" : ""}`}>
          <table className="w-full text-left">
            <caption className="sr-only">Evaluation metrics, cold start versus warm memory{mock ? " (MOCK run)" : ""}</caption>
            <thead>
              <tr className="border-b border-line text-base text-muted">
                <th scope="col" className="px-5 py-4 font-bold">Metric</th>
                <th scope="col" className="px-5 py-4 text-right font-bold">Cold</th>
                <th scope="col" className="px-5 py-4 text-right font-bold">Warm</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((r) => {
                const c = sb.cold![r.key];
                const w = sb.warm![r.key];
                const improved = r.better === "up" ? w > c : w < c;
                return (
                  <tr key={r.key} className="border-b border-line/70 last:border-0">
                    <th scope="row" className="px-5 py-4 text-lg font-bold">{r.label}</th>
                    <td className="px-5 py-4 text-right text-xl tabular-nums text-muted">{r.fmt(c)}</td>
                    <td className="px-5 py-4 text-right text-2xl font-bold tabular-nums">
                      {r.fmt(w)}{" "}
                      {w !== c && (
                        <span className={improved ? "text-voice" : "text-danger"} aria-label={improved ? "better" : "worse"}>{w > c ? "▲" : "▼"}</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {sb && (
        <p className="text-base text-muted">
          {sb.notes}{sb.cold && ` · ${sb.cold.runs} run${sb.cold.runs === 1 ? "" : "s"}`} · updated {new Date(sb.updated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}
