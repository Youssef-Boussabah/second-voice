import { useCallback, useEffect, useState } from "react";
import type { ConfigMetrics, Scoreboard } from "../contracts";
import { api } from "../lib/api";
import { Button } from "../components/ui";

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

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-bold">Cold vs warm memory</h1>
        <Button tone="ghost" onClick={load} aria-label="Refresh scoreboard">↻ Refresh</Button>
      </div>
      {err && <p className="rounded-2xl bg-red-50 p-4 text-xl text-red-800">Scoreboard unavailable: {err}</p>}
      {!sb && !err && <p className="text-xl text-muted">Loading…</p>}
      {sb && (!sb.cold || !sb.warm) && <p className="rounded-2xl bg-white p-4 text-xl text-muted">No eval runs yet. Run the eval to fill this in.</p>}
      {sb?.cold && sb.warm && (
        <table className="w-full border-separate border-spacing-y-2 text-left">
          <caption className="sr-only">Evaluation metrics, cold start versus warm memory</caption>
          <thead>
            <tr className="text-lg text-muted">
              <th scope="col" className="px-4">Metric</th>
              <th scope="col" className="px-4 text-right">Cold (no memory)</th>
              <th scope="col" className="px-4 text-right">Warm (with memory)</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => {
              const c = sb.cold![r.key];
              const w = sb.warm![r.key];
              const improved = r.better === "up" ? w > c : w < c;
              const same = w === c;
              return (
                <tr key={r.key} className="bg-white text-2xl">
                  <th scope="row" className="rounded-l-2xl px-4 py-4 text-xl font-bold">{r.label}</th>
                  <td className="px-4 py-4 text-right tabular-nums text-muted">{r.fmt(c)}</td>
                  <td className="rounded-r-2xl px-4 py-4 text-right text-3xl font-bold tabular-nums">
                    {r.fmt(w)}{" "}
                    {!same && (
                      <span className={improved ? "text-sage" : "text-red-700"} aria-label={improved ? "better" : "worse"}>
                        {w > c ? "▲" : "▼"}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {sb && (
        <p className="text-lg text-muted">
          {sb.notes || "Same scripted conversations replayed with memory off (cold) and on (warm)."}
          {sb.cold && ` · ${sb.cold.runs} runs`} · updated {new Date(sb.updated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}
