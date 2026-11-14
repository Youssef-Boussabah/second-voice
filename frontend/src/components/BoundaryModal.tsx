import { Button, Sheet } from "./ui";
import SensitiveText from "./SensitiveText";
import Icon from "./Icon";
import { listJoin, scopeLabel, topicLabel, useStore } from "../store";

/** A learned rule that conflicts with something Maya actually said: she decides. */
export default function BoundaryModal() {
  const b = useStore((s) => s.proposed);
  const people = useStore((s) => s.people);
  const resolve = useStore((s) => s.resolveProposed);
  if (!b) return null;
  return (
    <Sheet title="Keep this private?" onClose={() => void resolve(false)} labelledBy="proposed-title" icon="lock">
      <p className="text-2xl leading-snug">
        Keep <strong>{listJoin(b.topics.map(topicLabel))}</strong> private with <strong>{scopeLabel(b, people)}</strong>?
      </p>
      {b.evidence.rejected_text && (
        <p className="mt-4 rounded-3xl border border-line bg-surface p-4 text-xl text-muted">
          <span className="mb-2 block">Because you marked a reply as too personal.</span>
          <SensitiveText text={b.evidence.rejected_text} />
        </p>
      )}
      <p className="mt-4 flex items-start gap-2 text-lg text-muted">
        <Icon name="info" size={22} className="mt-0.5" />
        I checked {b.validation.replayed} past replies: {b.validation.conflicts} you actually chose to say would now be hidden, so I'm asking first.
      </p>
      <div className="mt-6 grid grid-cols-2 gap-4">
        <Button tone="secondary" className="min-h-20 text-2xl" onClick={() => void resolve(false)}>No, don't</Button>
        <Button tone="lock" className="min-h-20 text-2xl" onClick={() => void resolve(true)}>Yes, keep private</Button>
      </div>
    </Sheet>
  );
}
