import { useEffect } from "react";
import { USE_MOCKS } from "./config";
import { useStore, type Screen } from "./store";
import TalkScreen from "./screens/TalkScreen";
import MemoryScreen from "./screens/MemoryScreen";
import ScoreboardScreen from "./screens/ScoreboardScreen";
import Toasts from "./components/Toasts";
import ErrorBoundary from "./components/ErrorBoundary";
import BoundaryModal from "./components/BoundaryModal";
import Icon, { Logo, type IconName } from "./components/Icon";

const TABS: { id: Screen; label: string; short: string; icon: IconName }[] = [
  { id: "talk", label: "Talk", short: "Talk", icon: "chat" },
  { id: "memory", label: "Memory & privacy", short: "Memory", icon: "shield" },
  { id: "scoreboard", label: "Evaluation", short: "Eval", icon: "chart" },
];

const STATUS = {
  open: { text: "Live", dot: "bg-voice", ring: "ring-voice/25" },
  idle: { text: "Ready", dot: "bg-line-strong", ring: "ring-transparent" },
  connecting: { text: "Connecting…", dot: "bg-amber-500 animate-pulse", ring: "ring-amber-300/40" },
  closed: { text: "Reconnecting…", dot: "bg-danger animate-pulse", ring: "ring-danger/25" },
} as const;

export default function App() {
  const screen = useStore((s) => s.screen);
  const setScreen = useStore((s) => s.setScreen);
  const init = useStore((s) => s.init);
  const wsStatus = useStore((s) => s.wsStatus);
  const st = STATUS[wsStatus];

  useEffect(() => {
    void init();
  }, [init]);

  return (
    <div className="flex h-full flex-col">
      <header className="z-30 flex shrink-0 items-center gap-3 border-b border-line/80 bg-canvas/80 px-4 py-2.5 backdrop-blur-md sm:px-5">
        <div className="flex shrink-0 items-center gap-3">
          <Logo />
          <div className="hidden leading-tight xl:block">
            <p className="text-xl font-bold tracking-tight">Second Voice</p>
            <p className="text-sm text-muted">Maya's conversation co-pilot</p>
          </div>
        </div>
        <nav aria-label="Main" className="mx-auto flex gap-1 rounded-[22px] border border-line bg-surface/80 p-1 shadow-card">
          {TABS.map((t) => {
            const on = screen === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setScreen(t.id)}
                aria-current={on ? "page" : undefined}
                aria-label={t.label}
                className={`inline-flex min-h-16 items-center gap-2 whitespace-nowrap rounded-[18px] px-4 text-lg font-bold transition-colors sm:px-5 ${
                  on ? "bg-ink text-white shadow-card" : "text-muted hover:bg-ink/5 hover:text-ink"
                }`}
              >
                <Icon name={t.icon} size={22} />
                <span className="hidden lg:inline">{t.label}</span>
                <span className="lg:hidden">{t.short}</span>
              </button>
            );
          })}
        </nav>
        <div className="flex shrink-0 items-center gap-2">
          {USE_MOCKS && <span className="rounded-full bg-amber-soft px-3 py-1.5 text-base font-bold text-amber" title="VITE_USE_MOCKS=true">Mock data</span>}
          <span role="status" aria-live="polite"
            className={`flex items-center gap-2 rounded-full bg-surface px-3.5 py-2 text-base font-bold text-muted shadow-inset ring-4 ${st.ring}`}>
            <span aria-hidden className={`h-2.5 w-2.5 rounded-full ${st.dot}`} />
            <span className="hidden sm:inline">{st.text}</span>
            <span className="sr-only sm:hidden">{st.text}</span>
          </span>
        </div>
      </header>

      <main className="scroll-soft min-h-0 flex-1 overflow-y-auto">
        <ErrorBoundary key={screen}>
          {screen === "talk" && <TalkScreen />}
          {screen === "memory" && <MemoryScreen />}
          {screen === "scoreboard" && <ScoreboardScreen />}
        </ErrorBoundary>
      </main>

      <Toasts />
      <BoundaryModal />
    </div>
  );
}
