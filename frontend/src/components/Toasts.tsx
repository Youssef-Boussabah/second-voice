import { useStore } from "../store";

const STYLE = {
  learned: "bg-lock text-white",
  memory: "bg-sage text-white",
  error: "bg-red-700 text-white",
  info: "bg-ink text-paper",
} as const;
const ICON = { learned: "🔒", memory: "🧠", error: "⚠️", info: "✓" } as const;

export default function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 top-2 z-50 flex flex-col items-center gap-3 px-4">
      {toasts.map((t) => (
        <div key={t.id} role="status" className={`pointer-events-auto flex w-full max-w-2xl animate-fadein items-start gap-3 rounded-2xl p-4 shadow-xl ${STYLE[t.tone]}`}>
          <span aria-hidden className="text-2xl">{ICON[t.tone]}</span>
          <div className="flex-1">
            <p className="text-xl font-bold">{t.title}</p>
            {t.body && <p className="text-lg opacity-90">{t.body}</p>}
          </div>
          <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss notification" className="min-h-12 min-w-12 rounded-xl text-2xl hover:bg-white/20">×</button>
        </div>
      ))}
    </div>
  );
}
