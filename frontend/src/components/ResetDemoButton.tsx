import { useEffect, useState } from "react";
import { useStore } from "../store";
import { Button } from "./ui";

/** Re-seeds the demo (POST /api/admin/reset-demo). Second tap within 4 s confirms. */
export default function ResetDemoButton({ className = "" }: { className?: string }) {
  const reset = useStore((s) => s.resetDemo);
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Button
      tone={armed ? "primary" : "ghost"}
      className={className}
      disabled={busy}
      aria-live="polite"
      onClick={async () => {
        if (!armed) return setArmed(true);
        setArmed(false);
        setBusy(true);
        await reset();
        setBusy(false);
      }}
    >
      {busy ? "Resetting…" : armed ? "Tap again to reset" : "↺ Reset demo"}
    </Button>
  );
}
