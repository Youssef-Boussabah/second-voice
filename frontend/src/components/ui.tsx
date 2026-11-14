import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useEffect, useRef } from "react";

type Tone = "primary" | "secondary" | "ghost" | "danger" | "sage";
const TONES: Record<Tone, string> = {
  primary: "bg-clay text-white hover:bg-clay-dark active:bg-clay-dark",
  secondary: "bg-white text-ink border-2 border-line hover:border-clay",
  ghost: "bg-transparent text-ink hover:bg-clay-soft",
  danger: "bg-white text-clay-dark border-2 border-clay hover:bg-clay-soft",
  sage: "bg-sage text-white hover:brightness-110",
};

export function Button({ tone = "secondary", className = "", children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: Tone }) {
  return (
    <button
      type="button"
      {...rest}
      className={`min-h-16 rounded-2xl px-6 text-xl font-bold transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${TONES[tone]} ${className}`}
    >
      {children}
    </button>
  );
}

/** Bottom sheet / modal with focus trap-lite: focuses first control, Escape closes. */
export function Sheet({ title, onClose, children, labelledBy = "sheet-title" }: { title: string; onClose: () => void; children: ReactNode; labelledBy?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, textarea, input")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-ink/40 sm:items-center" onClick={onClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        className="w-full max-w-2xl animate-fadein rounded-t-3xl bg-paper p-6 shadow-2xl sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id={labelledBy} className="mb-4 text-2xl font-bold">{title}</h2>
        {children}
      </div>
    </div>
  );
}
