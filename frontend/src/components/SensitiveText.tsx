import { useEffect, useState } from "react";
import Icon from "./Icon";

const AUTO_HIDE_MS = 10_000;

/** Text that a privacy rule protects (e.g. a reply Maya marked "too personal").
 *  Hidden by default, including from screen readers and the DOM: it only renders after an
 *  intentional tap on "Show", and hides itself again after 10 s or when unmounted. */
export default function SensitiveText({ text, what = "reply" }: { text: string; what?: string }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!shown) return;
    const t = window.setTimeout(() => setShown(false), AUTO_HIDE_MS);
    return () => window.clearTimeout(t);
  }, [shown]);

  if (!shown) {
    return (
      <button type="button" data-sensitive onClick={() => setShown(true)} aria-label={`Show the hidden ${what}`}
        className="inline-flex min-h-16 items-center gap-2 rounded-2xl bg-ink/[.05] px-4 text-lg font-bold text-muted transition-colors hover:bg-ink/10 hover:text-ink">
        <Icon name="lock" size={20} /> Sensitive {what} hidden · Show
      </button>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <q className="text-xl text-ink">{text}</q>
      <button type="button" onClick={() => setShown(false)} aria-label={`Hide the ${what} again`}
        className="inline-flex min-h-16 items-center gap-2 rounded-2xl px-3 text-lg font-bold text-muted hover:bg-ink/5 hover:text-ink">
        <Icon name="x" size={20} /> Hide
      </button>
    </span>
  );
}
