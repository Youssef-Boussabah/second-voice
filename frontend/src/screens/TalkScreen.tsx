import { ContextHeader, PartnerPicker } from "../components/PartnerBar";
import { Button } from "../components/ui";
import Suggestions from "../components/Suggestions";
import { IncomingInput, Transcript, WhosThis } from "../components/Incoming";
import { useLandscape } from "../lib/useLandscape";
import { useStore } from "../store";
import ResetDemoButton from "../components/ResetDemoButton";

function EndButton() {
  const session = useStore((s) => s.session);
  const end = useStore((s) => s.endConversation);
  if (!session) return null;
  return (
    <Button tone="danger" className="shrink-0" onClick={() => void end()} aria-label="End conversation and save memory">
      End chat
    </Button>
  );
}

export default function TalkScreen() {
  const personId = useStore((s) => s.personId);
  const landscape = useLandscape();

  if (!personId) {
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-6 p-6">
        <h1 className="text-4xl font-bold">Who are you talking to?</h1>
        <p className="text-xl text-muted">Pick a person so replies fit them. You can switch any time.</p>
        <PartnerPicker />
        <ResetDemoButton className="mt-8 self-start text-lg text-muted" />
      </div>
    );
  }

  if (landscape) {
    // Cards are the hero: they start right under the one-line header.
    return (
      <div className="flex h-full flex-col gap-3 p-4">
        <div className="flex items-center justify-between gap-3">
          <ContextHeader />
          <EndButton />
        </div>
        <WhosThis />
        <div className="grid min-h-0 flex-1 grid-cols-[360px_1fr] gap-4">
          <section aria-label="Their side" className="flex min-h-0 flex-col gap-3 rounded-3xl bg-white/60 p-4">
            {/* pinned: switching person must always be one tap */}
            <div className="flex flex-wrap items-center gap-2">
              <PartnerPicker compact />
            </div>
            <div data-scrollbox className="min-h-0 flex-1 overflow-y-auto">
              <Transcript />
            </div>
            <IncomingInput />
          </section>
          <section aria-label="Reply suggestions" className="min-h-0 overflow-y-auto"><Suggestions /></section>
        </div>
      </div>
    );
  }

  // Portrait: who → replies → what they said → history.
  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-start justify-between gap-3">
        <PartnerPicker compact />
        <EndButton />
      </div>
      <ContextHeader />
      <WhosThis />
      <section aria-label="Reply suggestions"><Suggestions /></section>
      <section aria-label="Their side" className="flex flex-col gap-4 rounded-3xl bg-white/60 p-4">
        <IncomingInput />
        <Transcript />
      </section>
    </div>
  );
}
