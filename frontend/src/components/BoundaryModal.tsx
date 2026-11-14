import { Button, Sheet } from "./ui";
import { listJoin, scopeLabel, topicLabel, useStore } from "../store";

export default function BoundaryModal() {
  const b = useStore((s) => s.proposed);
  const people = useStore((s) => s.people);
  const resolve = useStore((s) => s.resolveProposed);
  if (!b) return null;
  return (
    <Sheet title="Keep this private?" onClose={() => void resolve(false)} labelledBy="proposed-title">
      <p className="text-2xl">
        Keep <strong>{listJoin(b.topics.map(topicLabel))}</strong> private with <strong>{scopeLabel(b, people)}</strong>?
      </p>
      {b.evidence.rejected_text && (
        <p className="mt-3 rounded-2xl bg-white p-4 text-xl text-muted">
          Because you rejected: <q className="text-ink">{b.evidence.rejected_text}</q>
        </p>
      )}
      <p className="mt-3 text-lg text-muted">
        Checked against {b.validation.replayed} past replies: {b.validation.conflicts} you actually sent would have been hidden.
      </p>
      <div className="mt-6 grid grid-cols-2 gap-4">
        <Button tone="secondary" className="min-h-20 text-2xl" onClick={() => void resolve(false)}>No, don't</Button>
        <Button tone="primary" className="min-h-20 text-2xl" onClick={() => void resolve(true)}>Yes, keep private</Button>
      </div>
    </Sheet>
  );
}
