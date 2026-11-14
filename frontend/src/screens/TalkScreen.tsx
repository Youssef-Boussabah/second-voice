import { PartnerCard, PartnerPicker } from "../components/PartnerBar";
import Suggestions from "../components/Suggestions";
import { IncomingInput, Transcript, WhosThis } from "../components/Incoming";
import { useLandscape } from "../lib/useLandscape";
import { useStore } from "../store";
import ResetDemoButton from "../components/ResetDemoButton";
import Icon from "../components/Icon";

function Welcome() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-8 px-5 py-10 sm:py-14">
      <div className="flex flex-col gap-3">
        <span className="inline-flex w-fit items-center gap-2 rounded-full bg-surface px-3.5 py-1.5 text-base font-bold text-muted shadow-inset">
          <Icon name="shield" size={18} className="text-lock" /> Nothing is spoken without your tap
        </span>
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">Who are you talking to?</h1>
        <p className="max-w-2xl text-xl text-muted">Replies are shaped by your history with each person, and private topics stay with the people you trust. You can switch any time.</p>
      </div>
      <PartnerPicker layout="cards" />
      <ResetDemoButton className="self-start text-lg" />
    </div>
  );
}

function Conversation() {
  return (
    <section aria-label="Conversation" className="panel flex min-h-0 flex-1 flex-col overflow-hidden">
      <p className="eyebrow px-5 pt-4">Conversation</p>
      <div data-scrollbox className="scroll-soft min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-2"><Transcript /></div>
    </section>
  );
}

export default function TalkScreen() {
  const personId = useStore((s) => s.personId);
  const landscape = useLandscape();

  if (!personId) return <Welcome />;

  if (landscape) {
    // Tablet landscape / desktop: context rail on the left, the reply cards are the hero.
    return (
      <div className="mx-auto grid h-full max-w-[1500px] grid-cols-[minmax(300px,360px)_1fr] gap-5 p-5">
        <aside aria-label="Who and what" className="flex min-h-0 flex-col gap-4">
          <PartnerCard />
          <div>
            <p className="eyebrow mb-2">Switch person</p>
            <PartnerPicker />
          </div>
          <Conversation />
        </aside>
        <div className="scroll-soft flex min-h-0 flex-col gap-5 overflow-y-auto pb-2 pr-1">
          <WhosThis />
          <section aria-label="Reply suggestions"><Suggestions /></section>
          <div className="panel mt-auto p-4"><IncomingInput /></div>
        </div>
      </div>
    );
  }

  // Portrait / narrow: who → replies → what they said → conversation.
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 p-4 sm:p-5">
      <PartnerCard compact />
      <PartnerPicker />
      <WhosThis />
      <section aria-label="Reply suggestions"><Suggestions /></section>
      <div className="panel p-4"><IncomingInput /></div>
      <section aria-label="Conversation" className="panel p-4">
        <p className="eyebrow mb-2">Conversation</p>
        <Transcript />
      </section>
    </div>
  );
}
