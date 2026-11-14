import { useStore } from "../store";
import Icon, { type IconName } from "./Icon";

const STYLE = {
  learned: "bg-lock text-white",
  memory: "bg-voice text-white",
  error: "bg-danger text-white",
  info: "bg-ink text-white",
} as const;
const ICON: Record<keyof typeof STYLE, IconName> = { learned: "shield", memory: "memory", error: "alert", info: "check" };

export default function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);
  return (
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-3 px-4 landscape:min-[960px]:inset-x-auto landscape:min-[960px]:bottom-5 landscape:min-[960px]:left-5 landscape:min-[960px]:w-[400px] landscape:min-[960px]:items-stretch landscape:min-[960px]:px-0">
      {toasts.map((t) => (
        <div key={t.id} role="status" className={`pointer-events-auto flex w-full max-w-2xl animate-pop items-start gap-4 rounded-3xl p-4 pl-5 shadow-lift ${STYLE[t.tone]}`}>
          <span className="mt-0.5 grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-white/15"><Icon name={ICON[t.tone]} /></span>
          <div className="flex-1 py-1">
            <p className="text-xl font-bold leading-snug">{t.title}</p>
            {t.body && <p className="mt-0.5 text-lg leading-snug text-white/90">{t.body}</p>}
          </div>
          <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss notification"
            className="grid min-h-12 min-w-12 place-items-center rounded-2xl hover:bg-white/15"><Icon name="x" /></button>
        </div>
      ))}
    </div>
  );
}
