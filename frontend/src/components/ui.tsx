import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useEffect, useRef } from "react";
import Icon from "./Icon";

type Tone = "primary" | "secondary" | "ghost" | "danger" | "sage" | "voice" | "lock";
const TONES: Record<Tone, string> = {
  primary: "bg-ink text-white shadow-card hover:bg-ink-soft",
  secondary: "bg-surface text-ink border border-line-strong shadow-card hover:border-ink/40",
  ghost: "bg-transparent text-ink hover:bg-ink/5",
  danger: "bg-surface text-danger border border-danger/30 hover:bg-danger-soft",
  sage: "bg-voice text-white shadow-card hover:bg-voice-dark",
  voice: "bg-voice text-white shadow-card hover:bg-voice-dark",
  lock: "bg-lock text-white shadow-card hover:bg-lock-dark",
};

export function Button({ tone = "secondary", className = "", children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  return (
    <button
      type="button"
      {...rest}
      className={`inline-flex min-h-16 items-center justify-center gap-2.5 rounded-2xl px-6 text-xl font-bold transition-[background-color,border-color,transform,box-shadow] duration-150 active:scale-[.98] disabled:cursor-not-allowed disabled:border-line disabled:bg-line/70 disabled:text-muted disabled:shadow-none ${TONES[tone]} ${className}`}
    >
      {children}
    </button>
  );
}

export function IconButton({ icon, label, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: Parameters<typeof Icon>[0]["name"]; label: string }) {
  return (
    <button type="button" aria-label={label} title={label} {...rest}
      className={`grid h-16 w-16 shrink-0 place-items-center rounded-2xl text-muted transition-colors hover:bg-ink/5 hover:text-ink disabled:opacity-40 ${className}`}>
      <Icon name={icon} size={26} />
    </button>
  );
}

const TONE_CHIP = {
  neutral: "bg-ink/[.05] text-muted",
  voice: "bg-voice-soft text-voice-dark",
  lock: "bg-lock-soft text-lock-dark",
  clay: "bg-clay-soft text-clay-dark",
  amber: "bg-amber-soft text-amber",
} as const;

export function Chip({ tone = "neutral", children, className = "" }: { tone?: keyof typeof TONE_CHIP; children: ReactNode; className?: string }) {
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-base font-bold ${TONE_CHIP[tone]} ${className}`}>{children}</span>;
}

/** Modal sheet: focuses the first control, Escape closes, focus returns to the opener. */
export function Sheet({ title, onClose, children, labelledBy = "sheet-title", icon }: { title: string; onClose: () => void; children: ReactNode; labelledBy?: string; icon?: Parameters<typeof Icon>[0]["name"] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    // never land initial focus on a control that reveals sensitive text (a stray Enter would show it)
    const root = ref.current;
    (root?.querySelector<HTMLElement>("[data-autofocus]")
      ?? root?.querySelector<HTMLElement>("textarea, input, button:not([data-close]):not([data-sensitive])")
      ?? root?.querySelector<HTMLElement>("[data-close]"))?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex animate-fadein items-end justify-center bg-ink/45 p-0 backdrop-blur-[2px] sm:items-center sm:p-6" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className="max-h-[92vh] w-full max-w-2xl animate-pop overflow-y-auto rounded-t-[32px] bg-canvas p-6 shadow-lift sm:rounded-[32px] sm:p-7"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-center gap-3">
          {icon && <span className="grid h-12 w-12 place-items-center rounded-2xl bg-surface text-ink shadow-card"><Icon name={icon} /></span>}
          <h2 id={labelledBy} className="flex-1 text-2xl font-bold">{title}</h2>
          <IconButton icon="x" label="Close" data-close onClick={onClose} />
        </div>
        {children}
      </div>
    </div>
  );
}
