import { ContextHeader, PartnerPicker } from "../components/PartnerBar";
import { Button } from "../components/ui";
import { useStore } from "../store";

export default function TalkScreen() {
  const personId = useStore((s) => s.personId);
  const session = useStore((s) => s.session);
  const end = useStore((s) => s.endConversation);

  if (!personId) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <h1 className="text-4xl font-bold">Who are you talking to?</h1>
        <p className="text-xl text-muted">Pick a person so replies fit them. You can switch any time.</p>
        <PartnerPicker />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <ContextHeader />
        {session && (
          <Button tone="danger" onClick={() => void end()} aria-label="End conversation and save memory">
            End conversation
          </Button>
        )}
      </div>
      <details className="rounded-2xl bg-white/60 p-2">
        <summary className="flex min-h-12 cursor-pointer items-center px-2 text-lg font-bold text-muted">Switch person</summary>
        <div className="pt-2"><PartnerPicker compact /></div>
      </details>
    </div>
  );
}
